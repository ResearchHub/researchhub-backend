import logging
import re

from research_ai.constants import DEFAULT_EMAIL_TEMPLATE_KEY
from research_ai.prompts.email_prompts import build_email_prompt
from research_ai.services.bedrock_llm_service import BedrockLLMService

logger = logging.getLogger(__name__)


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
    match = re.match(r"(?i)^Subject:\s*(.+)\n([\s\S]*)", body)
    if match:
        subject = match.group(1).strip()
        body = match.group(2).strip()
    return subject, body


def generate_expert_email(
    expert_name: str,
    expert_title: str = "",
    expert_affiliation: str = "",
    expertise: str = "",
    notes: str = "",
    template: str = DEFAULT_EMAIL_TEMPLATE_KEY,
    custom_use_case: str | None = None,
    outreach_context: str | None = None,
    template_data: dict | None = None,
) -> tuple[str, str]:
    """
    Generate subject and body for an expert outreach email using Bedrock.

    template: one of collaboration, consultation, conference, peer-review,
              publication, rfp-outreach, custom. For custom, pass custom_use_case.
    outreach_context: optional context from sender's template (included in prompt).
    template_data: optional dict (contact_name, contact_title, etc.)
                   for placeholder replacement and signature block.

    Returns:
        (email_subject, email_body)
    """
    prompt = build_email_prompt(
        expert_name=expert_name or "",
        expert_title=expert_title or "",
        expert_affiliation=expert_affiliation or "",
        expertise=expertise or "",
        notes=notes or "",
        template=template,
        custom_use_case=custom_use_case,
        outreach_context=outreach_context,
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
