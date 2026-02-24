import os

from research_ai.constants import EMAIL_TEMPLATE_PROMPT_FILES

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_email_template_cache: dict[str, str] = {}


def _load_email_template(name: str) -> str:
    """Load a prompt template from the prompts directory. Results are cached."""
    if name not in _email_template_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            _email_template_cache[name] = f.read()
    return _email_template_cache[name]


def build_email_prompt(
    expert_name: str,
    expert_title: str,
    expert_affiliation: str,
    expertise: str,
    notes: str,
    template: str,
    custom_use_case: str | None = None,
    outreach_context: str | None = None,
) -> str:
    """
    Build the full user prompt for email generation.

    template: one of collaboration, consultation, conference, peer-review,
              publication, rfp-outreach, or custom (use custom_use_case for custom).
    outreach_context: optional context from the sender's template (purpose, venue, etc.).
    """
    base_rules = _load_email_template("email_base_rules.txt").strip()
    common_raw = _load_email_template("email_common_instructions.txt")
    common = common_raw.format(base_rules=base_rules)

    sender_info = f"""Expert Name: {expert_name or 'N/A'}
Title: {expert_title or 'N/A'}
Affiliation: {expert_affiliation or 'N/A'}
Expertise: {expertise or 'N/A'}
Additional Context: {notes or 'N/A'}"""
    if outreach_context and outreach_context.strip():
        sender_info += f"""

Outreach context / sender's purpose (use this to tailor the email):
{outreach_context.strip()}"""

    filename = EMAIL_TEMPLATE_PROMPT_FILES.get(template, "email_default.txt")
    body_tpl = _load_email_template(filename)

    kwargs = {
        "sender_info": sender_info,
        "common": common,
        "custom_use_case": custom_use_case or "",
    }
    return body_tpl.format(**kwargs)
