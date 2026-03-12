import re
from typing import Any

# Supported variable names per entity (for documentation and optional validation).
# To extend: add keys here and in _build_*_context.
# See EMAIL_TEMPLATE_VARIABLES.md in this directory; update that README when changing
# entities or properties below.
USER_VARIABLES = (
    "email",
    "full_name",
    "first_name",
    "last_name",
    "headline",
    "organization",
)
RFP_VARIABLES = ("title", "deadline", "blurb", "amount", "url")
EXPERT_VARIABLES = ("name", "title", "affiliation", "email", "expertise")

# Regex for {{entity.field}} placeholders.
VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\.(\w+)\}\}")


def _build_user_context(user) -> dict[str, str]:
    """Build user entity dict for variable replacement."""
    if not user:
        return dict.fromkeys(USER_VARIABLES, "")
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    if not isinstance(first, str):
        first = ""
    if not isinstance(last, str):
        last = ""
    full_name = " ".join(
        part.strip() for part in [first, last] if part and str(part).strip()
    ).strip()
    headline = ""
    ap = getattr(user, "author_profile", None)
    if ap:
        h = getattr(ap, "headline", "") or ""
        headline = h.strip() if isinstance(h, str) else ""
    org = getattr(user, "organization", None)
    organization = ""
    if org is not None:
        n = getattr(org, "name", "") or ""
        organization = n.strip() if isinstance(n, str) else ""
    email_val = getattr(user, "email", "") or ""
    email_str = email_val.strip() if isinstance(email_val, str) else ""
    return {
        "email": email_str,
        "full_name": full_name,
        "first_name": first.strip(),
        "last_name": last.strip(),
        "headline": headline,
        "organization": organization,
    }


def _build_rfp_context(rfp_context_dict: dict | None) -> dict[str, str]:
    """Build rfp entity dict from build_rfp_context() result."""
    if not rfp_context_dict:
        return dict.fromkeys(RFP_VARIABLES, "")
    return {
        "title": (rfp_context_dict.get("title") or "").strip(),
        "deadline": (rfp_context_dict.get("deadline") or "").strip(),
        "blurb": (rfp_context_dict.get("blurb") or "").strip(),
        "amount": (rfp_context_dict.get("amount") or "").strip(),
        "url": (rfp_context_dict.get("url") or "").strip(),
    }


def _build_expert_context(resolved_expert: dict | None) -> dict[str, str]:
    """Build expert entity dict from resolve_expert_from_search() result."""
    if not resolved_expert:
        return dict.fromkeys(EXPERT_VARIABLES, "")
    return {
        "name": (resolved_expert.get("name") or "").strip(),
        "title": (resolved_expert.get("title") or "").strip(),
        "affiliation": (resolved_expert.get("affiliation") or "").strip(),
        "email": (resolved_expert.get("email") or "").strip(),
        "expertise": (resolved_expert.get("expertise") or "").strip(),
    }


def build_replacement_context(
    user=None,
    resolved_expert: dict | None = None,
    rfp_context_dict: dict | None = None,
) -> dict[str, dict[str, str]]:
    """
    Build nested context for {{entity.field}} replacement.
    Returns {"user": {...}, "rfp": {...}, "expert": {...}}.
    """
    result = {
        "user": _build_user_context(user),
        "rfp": _build_rfp_context(rfp_context_dict),
        "expert": _build_expert_context(resolved_expert),
    }
    return result


def replace_template_variables(text: str, context: dict[str, dict[str, Any]]) -> str:
    """
    Replace all {{entity.field}} placeholders in text with context values.
    Unknown entity.field are replaced with empty string.
    """
    if not text:
        return text

    def repl(match: re.Match) -> str:
        entity, field = match.group(1), match.group(2)
        value = context.get(entity, {}).get(field, "")
        return str(value) if value is not None else ""

    return VARIABLE_PATTERN.sub(repl, text)
