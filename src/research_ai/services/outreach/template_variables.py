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
PROPOSAL_VARIABLES = (
    "title",
    "url",
    "created_by_name",
    "goal_amount",
    "amount_raised",
    "contributor_count",
    "deadline",
    "blurb",
)
EXPERT_VARIABLES = ("name", "title", "affiliation", "email", "expertise")


def format_expert_name_from_raw(raw: str) -> str:
    """
    Stored expert_name / {{expert.name}}: keep first and last token; drop middle.
    """
    s = " ".join((raw or "").split())
    if not s:
        return ""
    tokens = s.split()
    if len(tokens) == 1:
        return tokens[0]
    return f"{tokens[0]} {tokens[-1]}"


# Regex for {{entity.field}} placeholders.
VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\.(\w+)\}\}")


def extract_placeholder_pairs(*texts: str) -> frozenset[tuple[str, str]]:
    """Return the set of (entity, field) pairs found across the given texts."""
    pairs: set[tuple[str, str]] = set()
    for text in texts:
        if not text:
            continue
        pairs.update(
            (entity, field) for entity, field in VARIABLE_PATTERN.findall(text)
        )
    return frozenset(pairs)


def flatten_variable_key(entity: str, field: str) -> str:
    """Map ResearchHub ``entity.field`` to provider ``entity_field``."""
    return f"{entity}_{field}"


def flatten_placeholders_for_provider(text: str) -> str:
    """
    Rewrite ``{{entity.field}}`` placeholders to provider ``{{entity_field}}``.

    Outreach provider custom variables are flat strings; ResearchHub templates
    use dotted entity.field form.
    """
    if not text:
        return text

    def repl(match: re.Match) -> str:
        return "{{" + flatten_variable_key(match.group(1), match.group(2)) + "}}"

    return VARIABLE_PATTERN.sub(repl, text)


def published_variable_keys(*texts: str) -> list[str]:
    """Sorted provider custom_variable keys from ResearchHub placeholders."""
    return sorted(
        flatten_variable_key(entity, field)
        for entity, field in extract_placeholder_pairs(*texts)
    )


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


def _build_proposal_context(proposal_context_dict: dict | None) -> dict[str, str]:
    """Build proposal entity dict from build_proposal_context() result."""
    if not proposal_context_dict:
        return dict.fromkeys(PROPOSAL_VARIABLES, "")
    return {
        "title": (proposal_context_dict.get("title") or "").strip(),
        "url": (proposal_context_dict.get("url") or "").strip(),
        "created_by_name": (proposal_context_dict.get("created_by_name") or "").strip(),
        "goal_amount": (proposal_context_dict.get("goal_amount") or "").strip(),
        "amount_raised": (proposal_context_dict.get("amount_raised") or "").strip(),
        "contributor_count": (
            proposal_context_dict.get("contributor_count") or ""
        ).strip(),
        "deadline": (proposal_context_dict.get("deadline") or "").strip(),
        "blurb": (proposal_context_dict.get("blurb") or "").strip(),
    }


def _build_expert_context(resolved_expert: dict | None) -> dict[str, str]:
    """Build expert entity dict from ``ExpertDisplay.email_generation_dict`` output."""
    if not resolved_expert:
        return dict.fromkeys(EXPERT_VARIABLES, "")
    return {
        "name": format_expert_name_from_raw(resolved_expert.get("name") or ""),
        "title": (resolved_expert.get("title") or "").strip(),
        "affiliation": (resolved_expert.get("affiliation") or "").strip(),
        "email": (resolved_expert.get("email") or "").strip(),
        "expertise": (resolved_expert.get("expertise") or "").strip(),
    }


def build_replacement_context(
    user=None,
    resolved_expert: dict | None = None,
    rfp_context_dict: dict | None = None,
    proposal_context_dict: dict | None = None,
) -> dict[str, dict[str, str]]:
    """
    Build nested context for {{entity.field}} replacement.
    Returns {"user": {...}, "rfp": {...}, "proposal": {...}, "expert": {...}}.
    """
    result = {
        "user": _build_user_context(user),
        "rfp": _build_rfp_context(rfp_context_dict),
        "proposal": _build_proposal_context(proposal_context_dict),
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


def flatten_context_for_provider(
    context: dict[str, dict[str, Any]],
) -> dict[str, str]:
    """Flatten nested ``{{entity.field}}`` context to provider custom_variables."""
    result: dict[str, str] = {}
    for entity, fields in (context or {}).items():
        if not isinstance(fields, dict):
            continue
        for field, value in fields.items():
            key = flatten_variable_key(str(entity), str(field))
            result[key] = "" if value is None else str(value)
    return result


def custom_variables_for_published_keys(
    context: dict[str, dict[str, Any]],
    published_keys: list[str] | tuple[str, ...] | None,
) -> dict[str, str]:
    """Return provider custom_variables for the published keys only (strings)."""
    flat = flatten_context_for_provider(context)
    keys = list(published_keys or [])
    return {key: flat.get(key, "") for key in keys}


def missing_published_variables(
    context: dict[str, dict[str, Any]],
    published_keys: list[str] | tuple[str, ...] | None,
) -> list[str]:
    """Return published provider keys that are missing or blank in ``context``."""
    custom = custom_variables_for_published_keys(context, published_keys)
    return sorted(key for key, value in custom.items() if not (value or "").strip())
