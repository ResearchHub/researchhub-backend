import os

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_template_cache: dict[str, str] = {}


def _load_template(name: str) -> str:
    if name not in _template_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            _template_cache[name] = f.read()
    return _template_cache[name]


def get_rfp_summary_system_prompt() -> str:
    return _load_template("rfp_summary_system.txt")


def build_rfp_summary_user_prompt(grant_text: str) -> str:
    text = (grant_text or "").strip()
    if len(text) > 100000:
        text = text[:100000] + "\n\n[TRUNCATED FOR LENGTH]"
    return "Summarize the following RFP / funding opportunity material:\n\n" + text


def get_grant_executive_summary_system_prompt() -> str:
    return _load_template("grant_executive_summary_system.txt")
