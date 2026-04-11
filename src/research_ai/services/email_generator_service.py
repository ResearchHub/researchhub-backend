import logging
import re

from research_ai.constants import BASE_FRONTEND_URL, DEFAULT_EMAIL_TEMPLATE_KEY
from research_ai.prompts.email_prompts import build_email_prompt
from research_ai.services.bedrock_llm_service import BedrockLLMService
from research_ai.services.email_template_service import (
    get_template as get_email_template,
)
from research_ai.services.email_template_variables import (
    _build_user_context,
    build_replacement_context,
    replace_template_variables,
)
from research_ai.services.expert_display import build_expert_display_name
from research_ai.services.expert_search_email_document_context import (
    format_document_context_for_llm,
    resolve_expert_search_email_document_context,
)

logger = logging.getLogger(__name__)

OTHER_GRANTS_URL = f"{BASE_FRONTEND_URL}/fund/grants"


def _normalize_signature_dict(data: dict | None) -> dict:
    """Normalize to keys used by _replace_placeholders and _build_signature_block."""
    if not data:
        return {}
    return {
        "name": (data.get("name") or "").strip(),
        "title": (data.get("title") or "").strip(),
        "institution": (data.get("institution") or "").strip(),
        "email": (data.get("email") or "").strip(),
        "phone": (data.get("phone") or "").strip(),
        "website": (data.get("website") or "").strip(),
    }


def normalize_llm_text_for_subject(text: str) -> str:
    """
    Normalize LLM subject line to plain text: literal backslash-n sequences from the
    LLM become newlines, then all whitespace collapses to single spaces (subjects
    must not contain HTML).
    """
    if not text:
        return text
    s = str(text).replace("\\n", "\n")
    return re.sub(r"\s+", " ", s).strip()


def normalize_llm_text_to_html(text: str) -> str:
    """
    Normalize LLM-generated email body for HTML: normalize literal backslash-n from
    the LLM to real newlines, then each line becomes its own <p>...</p>; blank lines
    become <p></p>.
    """
    if not text:
        return text
    result = text.replace("\\n", "\n")
    out: list[str] = []
    for part in result.split("\n"):
        if part.strip() == "":
            out.append("<p></p>")
        else:
            out.append(f"<p>{part}</p>")
    return "".join(out)


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
    # Name / title / email: only replace when non-empty so callers still see missing tokens.
    strict_placeholders = [
        ("[Your Name]", template_data.get("name")),
        ("[Your name]", template_data.get("name")),
        ("[NAME]", template_data.get("name")),
        ("[Your Title]", template_data.get("title")),
        ("[Your title]", template_data.get("title")),
        ("[Email]", template_data.get("email")),
        ("[Your Email]", template_data.get("email")),
        ("[Your email]", template_data.get("email")),
    ]
    for placeholder, value in strict_placeholders:
        if value and str(value).strip():
            result = result.replace(placeholder, str(value).strip())
    # Institution / phone / website: strip token when empty (clean LLM body + signature).
    optional_placeholders = [
        ("[Institution]", template_data.get("institution")),
        ("[Your Institution]", template_data.get("institution")),
        ("[Your institution]", template_data.get("institution")),
        ("[Organization]", template_data.get("institution")),
        (
            "[Your Organization/Institution Name]",
            template_data.get("institution"),
        ),
        ("[Phone]", template_data.get("phone")),
        ("[Your Phone]", template_data.get("phone")),
        ("[Website/Resources]", template_data.get("website")),
        ("[Website]", template_data.get("website")),
        ("[Resources]", template_data.get("website")),
    ]
    for placeholder, value in optional_placeholders:
        if value and str(value).strip():
            result = result.replace(placeholder, str(value).strip())
        else:
            result = result.replace(placeholder, "")
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


def _normalize_expert_from_resolved(resolved_expert: dict) -> dict:
    """Extract and normalize expert fields from resolved_expert dict."""
    title = resolved_expert.get("academic_title") or resolved_expert.get("title") or ""
    if not isinstance(title, str):
        title = ""
    return {
        "name": (resolved_expert.get("name") or "").strip(),
        "honorific": (resolved_expert.get("honorific") or "").strip(),
        "first_name": (resolved_expert.get("first_name") or "").strip(),
        "middle_name": (resolved_expert.get("middle_name") or "").strip(),
        "last_name": (resolved_expert.get("last_name") or "").strip(),
        "title": title.strip(),
        "affiliation": resolved_expert.get("affiliation") or "",
        "expertise": resolved_expert.get("expertise") or "",
        "notes": resolved_expert.get("notes") or "",
        "email": (resolved_expert.get("email") or "").strip(),
    }


def _build_llm_sender_signature_data(user) -> dict[str, str]:
    """Map User to keys used by _build_signature_block (limited fields)."""
    u = _build_user_context(user)
    return {
        "name": u.get("full_name") or "",
        "title": u.get("headline") or "",
        "institution": u.get("organization") or "",
        "email": u.get("email") or "",
        "phone": "",
        "website": "",
    }


def _format_sender_context_for_llm(user) -> str:
    """Human-readable sender block for LLM prompts from User / author_profile."""
    u = _build_user_context(user)
    lines = [
        f"Sender name: {u.get('full_name') or 'N/A'}",
        f"Sender email: {u.get('email') or 'N/A'}",
        f"Headline / role: {u.get('headline') or 'N/A'}",
        f"Organization: {u.get('organization') or 'N/A'}",
    ]
    return "\n".join(lines)


def _generate_with_fixed_template(
    et, expert_search, expert_dict: dict, user
) -> tuple[str, str]:
    """Generate subject/body using a fixed email template and variable replacement."""
    doc_ctx = resolve_expert_search_email_document_context(expert_search)
    expert_for_context = {
        "name": expert_dict["name"],
        "honorific": expert_dict.get("honorific") or "",
        "first_name": expert_dict.get("first_name") or "",
        "middle_name": expert_dict.get("middle_name") or "",
        "last_name": expert_dict.get("last_name") or "",
        "title": expert_dict["title"],
        "affiliation": expert_dict["affiliation"],
        "email": expert_dict["email"],
        "expertise": expert_dict["expertise"],
    }
    context = build_replacement_context(
        user=user,
        resolved_expert=expert_for_context,
        rfp_context_dict=doc_ctx.rfp_context_dict,
        proposal_context_dict=doc_ctx.proposal_context_dict,
    )
    subject = replace_template_variables((et.email_subject or "").strip(), context)
    body = replace_template_variables((et.email_body or "").strip(), context)
    return subject, body


def _generate_with_llm(
    expert_dict: dict,
    template: str,
    custom_use_case: str | None,
    expert_search,
    user,
) -> tuple[str, str]:
    """Generate subject/body via LLM, then post-process and append signature."""
    doc_ctx = resolve_expert_search_email_document_context(expert_search)
    sender_block = _format_sender_context_for_llm(user)
    document_block = format_document_context_for_llm(doc_ctx)

    expert_name_for_llm = build_expert_display_name(
        honorific=expert_dict.get("honorific") or "",
        first_name=expert_dict.get("first_name") or "",
        middle_name=expert_dict.get("middle_name") or "",
        last_name=expert_dict.get("last_name") or "",
        name_suffix="",
        fallback_name=expert_dict.get("name") or "",
    )
    prompt = build_email_prompt(
        expert_name=expert_name_for_llm or "",
        expert_title=expert_dict["title"] or "",
        expert_affiliation=expert_dict["affiliation"] or "",
        expertise=expert_dict["expertise"] or "",
        notes=expert_dict["notes"] or "",
        template=template,
        custom_use_case=custom_use_case,
        sender_context=sender_block,
        document_context=document_block,
    )
    service = BedrockLLMService()
    raw = service.invoke(
        system_prompt=EMAIL_SYSTEM_PROMPT,
        user_prompt=prompt,
        max_tokens=1024,
        temperature=0.3,
    )
    sig_source = _build_llm_sender_signature_data(user)
    normalized = _normalize_signature_dict(sig_source)
    text = _strip_markdown(raw)
    text = _strip_existing_signature(text, normalized if normalized else None)
    text = _replace_placeholders(text, normalized)
    if normalized:
        sig = _build_signature_block(normalized)
        if sig:
            text = text.rstrip() + sig
    subject, body = _parse_subject_and_body(text)
    subject = normalize_llm_text_for_subject(subject)
    body = normalize_llm_text_to_html(body)
    return subject, body


def generate_expert_email(
    resolved_expert: dict,
    template: str | None = DEFAULT_EMAIL_TEMPLATE_KEY,
    custom_use_case: str | None = None,
    expert_search=None,
    template_id: int | None = None,
    user=None,
) -> tuple[str, str]:
    """
    Generate subject and body for an expert outreach email.

    Returns:
        (email_subject, email_body)
    """
    expert_dict = _normalize_expert_from_resolved(resolved_expert)

    if template is None:
        if template_id is None:
            raise ValueError("template_id is required for fixed template generation.")
        et = get_email_template(template_id)
        if et is None:
            raise ValueError(f"EmailTemplate id={template_id} not found.")
        return _generate_with_fixed_template(et, expert_search, expert_dict, user)

    return _generate_with_llm(
        expert_dict,
        template,
        custom_use_case,
        expert_search,
        user,
    )
