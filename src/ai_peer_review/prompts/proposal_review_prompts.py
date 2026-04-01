import os

_PROMPTS_DIR = os.path.dirname(os.path.abspath(__file__))
_template_cache: dict[str, str] = {}


def _load_template(name: str) -> str:
    if name not in _template_cache:
        path = os.path.join(_PROMPTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            _template_cache[name] = f.read()
    return _template_cache[name]


def get_proposal_review_system_prompt() -> str:
    return _load_template("proposal_review_system.txt")


def build_proposal_review_user_prompt(
    proposal_text: str,
    rfp_context: str | None = None,
    author_context: str | None = None,
) -> str:
    ctx = ""
    if rfp_context and rfp_context.strip():
        ctx = (
            "\n\nRFP CONTEXT (from funding opportunity, align your review with this):\n"
            f"{rfp_context.strip()[:8000]}\n"
        )
    author = ""
    if author_context and author_context.strip():
        author = (
            "\n\nAUTHOR CONTEXT (from ResearchHub profile; use for feasibility / "
            "track record where relevant, do not invent facts beyond this):\n"
            f"{author_context.strip()}\n"
        )
    text = (proposal_text or "").strip()
    if len(text) > 120000:
        text = text[:120000] + "\n\n[TRUNCATED FOR LENGTH]"
    return (
        "Evaluate the following research proposal and return the structured JSON assessment "
        "with all five dimensions and narrative sections (editorial_summary, issue_table, "
        "feasibility_timeline_notes, budget_notes).\n\n"
        "PROPOSAL TEXT:\n"
        f"{text}"
        f"{author}"
        f"{ctx}"
    )
