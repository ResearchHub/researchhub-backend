import logging
import re

from django.conf import settings

from research_ai.constants import DEFAULT_EMAIL_TEMPLATE_KEY
from research_ai.models import EmailTemplate
from research_ai.prompts.email_prompts import build_email_prompt
from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.email_template_service import (
    get_template as get_email_template,
)
from research_ai.services.email_template_variables import (
    build_replacement_context,
    replace_template_variables,
)
from research_ai.services.rfp_email_context import build_rfp_context, resolve_grant

logger = logging.getLogger(__name__)

_BASE_FRONTEND_URL = getattr(
    settings, "BASE_FRONTEND_URL", "https://www.researchhub.com"
)
OTHER_GRANTS_URL = f"{_BASE_FRONTEND_URL}/fund/grants"


def _normalize_template_data(data: dict | None) -> dict:
    """Normalize template_data to keys: name, title, institution, email, phone, website."""
    if not data:
        return {}
    return {
        "name": (data.get("contact_name") or "").strip(),
        "title": (data.get("contact_title") or "").strip(),
        "institution": (data.get("contact_institution") or "").strip(),
        "email": (data.get("contact_email") or "").strip(),
        "phone": (data.get("contact_phone") or "").strip(),
        "website": (data.get("contact_website") or "").strip(),
    }


def _apply_sender_fallbacks(template_data: dict | None, expert_search) -> dict:
    """
    Fill missing sender name/title from the current user on the expert search.

    This is mainly used by the no-LLM RFP renderer when the user has not set up an
    email template yet.
    """
    normalized = _normalize_template_data(template_data)
    created_by = getattr(expert_search, "created_by", None)
    if not created_by:
        return normalized

    if not normalized.get("name"):
        full_name = " ".join(
            part.strip()
            for part in [
                getattr(created_by, "first_name", "") or "",
                getattr(created_by, "last_name", "") or "",
            ]
            if part and part.strip()
        )
        if full_name:
            normalized["name"] = full_name

    if not normalized.get("title"):
        author_profile = getattr(created_by, "author_profile", None)
        headline = ""
        if author_profile:
            headline = (getattr(author_profile, "headline", "") or "").strip()
        if headline:
            normalized["title"] = headline

    return normalized


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting (bold, italic, code, links)."""
    result = text
    result = re.sub(r"\*\*([^*]+)\*\*", r"\1", result)
    result = re.sub(r"__([^_]+)__", r"\1", result)
    result = re.sub(r"(?<!\*)\*(?!\*)([^*]+)\*(?!\*)", r"\1", result)
    result = re.sub(r"(?<!_)_(?!_)([^_]+)_(?!_)", r"\1", result)
    result = re.sub(r"`([^`]+)`", r"\1", result)
    result = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", result)
    return result


def _strip_existing_signature(text: str, template_data: dict | None) -> str:
    """Strip trailing signature/closing from LLM output. template_data = normalized dict."""
    result = text.strip()
    # 1. Cut at separator (--- or ——) in second half
    sep_match = re.search(r"\n\s*[-—]{2,}\s*\n", result)
    if sep_match and sep_match.start() > len(result) * 0.4:
        result = result[: sep_match.start()].strip()
    # 2. Find last closing phrase (signature is always at the end)
    closing_phrases = [
        "Best regards,",
        "Best,",
        "Sincerely,",
        "Thank you,",
        "Thanks,",
        "Warm regards,",
        "Kind regards,",
        "Regards,",
        "Cheers,",
        "Looking forward",
    ]
    closing_idx = -1
    for phrase in closing_phrases:
        idx = result.rfind(phrase)
        if idx != -1 and (closing_idx < 0 or idx > closing_idx):
            closing_idx = idx
    if closing_idx != -1:
        body_part = result[:closing_idx].strip()
        signature_part = result[closing_idx:]
        # 3. Strip placeholders only in the signature block (after closing phrase)
        signature_part = re.sub(r"\[Your Name\][\s\S]*$", "", signature_part)
        signature_part = re.sub(r"\[Name\][\s\S]*$", "", signature_part)
        signature_part = re.sub(r"\[Institution\][\s\S]*$", "", signature_part)
        signature_part = re.sub(r"\[Organization\][\s\S]*$", "", signature_part)
        signature_part = re.sub(
            r"\[Your Organization/Institution Name\][\s\S]*$", "", signature_part
        )

        # Keep body only; discard signature (we add our own later)
        result = body_part
    # else: do nothing, keep result as is
    # 4. Strip trailing lines that match template_data values
    if template_data:
        known = [
            v
            for v in [
                template_data.get("name"),
                template_data.get("title"),
                template_data.get("institution"),
                template_data.get("email"),
                template_data.get("phone"),
                template_data.get("website"),
            ]
            if v and v.strip()
        ]
        if known:
            lines = result.split("\n")
            while lines:
                last = lines[-1].strip()
                if not last:
                    lines.pop()
                    continue
                if any(last == v or last == v.strip() for v in known):
                    lines.pop()
                else:
                    break
            result = "\n".join(lines)
    return result.strip()


def _replace_placeholders(text: str, template_data: dict) -> str:
    """Replace [Your Name], [Institution], etc. with template_data values."""
    result = text
    placeholders = [
        ("[Your Name]", template_data.get("name")),
        ("[Your name]", template_data.get("name")),
        ("[NAME]", template_data.get("name")),
        ("[Your Title]", template_data.get("title")),
        ("[Your title]", template_data.get("title")),
        ("[Institution]", template_data.get("institution")),
        ("[Your Institution]", template_data.get("institution")),
        ("[Your institution]", template_data.get("institution")),
        ("[Organization]", template_data.get("institution")),
        ("[Email]", template_data.get("email")),
        ("[Your Email]", template_data.get("email")),
        ("[Your email]", template_data.get("email")),
        ("[Phone]", template_data.get("phone")),
        ("[Your Phone]", template_data.get("phone")),
        ("[Website/Resources]", template_data.get("website")),
        ("[Website]", template_data.get("website")),
        ("[Resources]", template_data.get("website")),
    ]
    for placeholder, value in placeholders:
        if value and value.strip():
            result = result.replace(placeholder, value)
    return result


def _build_signature_block(template_data: dict) -> str:
    """Build 'Best regards,\n\nname\ntitle\n...' from template_data."""
    parts = []
    for key in ("name", "title", "institution", "email", "phone", "website"):
        v = template_data.get(key)
        if v and str(v).strip():
            parts.append(str(v).strip())
    if not parts:
        return ""
    return "\n\nBest regards,\n\n" + "\n".join(parts)


EMAIL_SYSTEM_PROMPT = (
    "You are a professional email writer. Generate concise, authentic "
    "outreach emails. Follow the format and rules in the user message exactly."
)


def _parse_subject_and_body(text: str) -> tuple[str, str]:
    """
    Parse LLM output that should be in the form:
    Subject: [subject line]

    [Email body...]
    """
    subject = ""
    body = text.strip()
    match = re.match(r"(?i)^Subject:\s*([^\n]*)\n([\s\S]*)", body)  # NOSONAR
    if match:
        subject = match.group(1).strip()
        body = match.group(2).strip()
    return subject, body


def generate_expert_email(
    resolved_expert: dict,
    template: str = DEFAULT_EMAIL_TEMPLATE_KEY,
    custom_use_case: str | None = None,
    template_data: dict | None = None,
    expert_search=None,
    template_id: int | None = None,
    user=None,
) -> tuple[str, str]:
    """
    Generate subject and body for an expert outreach email.

    resolved_expert: dict with name, title, affiliation, expertise, email, notes
                     (e.g. from resolve_expert_from_search or from GeneratedEmail fields).

    Behavior is driven by template type when a template is provided:
    - If template (loaded by template_id + user) has template_type ``fixed-template``
      and context type is supported (e.g. RFP), subject/body are built from the
      template's email_subject/email_body with {{entity.field}} variable substitution;
      no LLM is used.
    - Otherwise (no template, or template_type ``prompt-context``): uses Bedrock LLM;
      template_data and outreach_context are derived from the template when present.

    template: one of collaboration, consultation, conference, peer-review,
              publication, rfp-outreach, custom. For custom, pass custom_use_case.
    template_data: optional override; else derived from template when loaded.
    expert_search: optional ExpertSearch used to derive RFP context for rfp-outreach.
    template_id: optional; with user, loads EmailTemplate.
    user: optional User; required with template_id to load template.

    Returns:
        (email_subject, email_body)
    """
    # Normalize expert fields from resolved_expert (view/task pass this dict only)
    expert_name = (resolved_expert.get("name") or "").strip()
    expert_title = resolved_expert.get("title") or ""
    expert_affiliation = resolved_expert.get("affiliation") or ""
    expertise = resolved_expert.get("expertise") or ""
    notes = resolved_expert.get("notes") or ""
    expert_email = (resolved_expert.get("email") or "").strip()

    # Load template by id when provided (view and task pass template_id + user only)
    et = None
    if template_id is not None and user is not None:
        et = get_email_template(user, template_id)

    # Fixed-template path: template exists and is fixed; for now only rfp-outreach is supported
    if (
        et is not None
        and getattr(et, "template_type", None) == EmailTemplate.TemplateType.FIXED
        and template == "rfp-outreach"
        and expert_search is not None
    ):
        grant = resolve_grant(expert_search=expert_search)
        rfp_context_dict = build_rfp_context(grant) if grant else None
        if rfp_context_dict:
            expert_for_context = {
                "name": expert_name,
                "title": expert_title,
                "affiliation": expert_affiliation,
                "email": expert_email,
                "expertise": expertise,
            }
            request_user = getattr(expert_search, "created_by", None) or user
            context = build_replacement_context(
                user=request_user,
                expert_search=expert_search,
                resolved_expert=expert_for_context,
                rfp_context_dict=rfp_context_dict,
            )
            subject = replace_template_variables(
                (et.email_subject or "").strip(), context
            )
            body = replace_template_variables((et.email_body or "").strip(), context)
            return subject, body
        # Fixed template but unsupported context or missing RFP data: fall back to LLM

    # LLM path: no template, or prompt-context template, or fixed template without RFP context
    # Derive outreach_context and template_data from template only when needed for AI generation
    outreach_context = None
    if et is not None:
        outreach_context = getattr(et, "outreach_context", "").strip() or None
        template_data = template_data or _normalize_template_data(
            {
                "contact_name": getattr(et, "contact_name", None) or "",
                "contact_title": getattr(et, "contact_title", None) or "",
                "contact_institution": getattr(et, "contact_institution", None) or "",
                "contact_email": getattr(et, "contact_email", None) or "",
                "contact_phone": getattr(et, "contact_phone", None) or "",
                "contact_website": getattr(et, "contact_website", None) or "",
            }
        )

    rfp_context = None
    if template == "rfp-outreach" and expert_search is not None:
        grant = resolve_grant(expert_search=expert_search)
        rfp_context = build_rfp_context(grant) if grant else None

    prompt = build_email_prompt(
        expert_name=expert_name or "",
        expert_title=expert_title or "",
        expert_affiliation=expert_affiliation or "",
        expertise=expertise or "",
        notes=notes or "",
        template=template,
        custom_use_case=custom_use_case,
        outreach_context=outreach_context,
        rfp_context=rfp_context,
    )
    service = BedrockLLMService()
    raw = service.invoke(
        system_prompt=EMAIL_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1024,
        temperature=0.3,
    )
    # Post-process: strip markdown, signature, replace placeholders, append signature
    normalized = _normalize_template_data(template_data)
    text = _strip_markdown(raw)
    text = _strip_existing_signature(text, normalized if normalized else None)
    text = _replace_placeholders(text, normalized)
    if normalized:
        sig = _build_signature_block(normalized)
        if sig:
            text = text.rstrip() + sig
    subject, body = _parse_subject_and_body(text)
    return subject, body
