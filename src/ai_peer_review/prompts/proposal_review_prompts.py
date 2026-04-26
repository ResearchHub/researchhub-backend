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


def get_proposal_key_insights_system_prompt() -> str:
    return _load_template("proposal_key_insights_system.txt")


def build_proposal_key_insights_user_prompt(
    proposal_text: str,
    rfp_context: str | None = None,
    ai_review_summary: str = "",
    human_reviews_text: str = "",
) -> str:
    """
    User message for the key-insights pass: proposal, RFP, AI review
    summary, and human review text. Truncation matches
    build_proposal_review_user_prompt for proposal (120k) and RFP (8k).
    """
    rfp = ""
    if rfp_context and rfp_context.strip():
        rfp = (
            "\n\nRFP CONTEXT (from funding opportunity; prefer alignment and "
            "fit when summarizing and when naming strengths/weaknesses):\n"
            f"{rfp_context.strip()[:8000]}\n"
        )
    ai = ""
    if ai_review_summary and ai_review_summary.strip():
        s = ai_review_summary.strip()
        if len(s) > 20000:
            s = s[:20000] + "\n\n[TRUNCATED FOR LENGTH]"
        ai = (
            "\n\nAI REVIEW SUMMARY (existing structured review on this proposal; use "
            "as an input signal, not a substitute for the proposal text):\n"
            f"{s}\n"
        )
    human = ""
    if human_reviews_text and human_reviews_text.strip():
        h = human_reviews_text.strip()
        if len(h) > 10000:
            h = h[:10000] + "\n\n[TRUNCATED FOR LENGTH]"
        human = (
            "\n\nHUMAN REVIEWS (RHF-ENDORSED: awarded or tipped by the ResearchHub "
            "Foundation account; use as peer signal where relevant):\n"
            f"{h}\n"
        )
    text = (proposal_text or "").strip()
    if len(text) > 120000:
        text = text[:120000] + "\n\n[TRUNCATED FOR LENGTH]"
    return (
        "Read the following inputs and return only the required JSON: a short tldr, "
        "a strengths list, and a weaknesses list. Order strengths and weaknesses by "
        "descending importance (index 0 is most important in each array). The tldr "
        "must be 2-3 sentences and at most 600 characters, covering what the "
        "proposal is about, RFP fit when context exists, one major highlight, and "
        "one major issue.\n\n"
        "PROPOSAL TEXT:\n"
        f"{text}"
        f"{rfp}"
        f"{ai}"
        f"{human}"
    )


def get_openai_web_context_system_prompt() -> str:
    """System instructions for OpenAI web search in proposal review."""
    return _load_template("openai_web_context_system.txt")


def build_proposal_review_user_prompt(
    proposal_text: str,
    rfp_context: str | None = None,
    author_context: str | None = None,
    external_researcher_context: str | None = None,
    web_search_context: str | None = None,
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
    external = ""
    if external_researcher_context and external_researcher_context.strip():
        external = (
            "\n\nEXTERNAL RESEARCHER CONTEXT (from ORCID public record and OpenAlex; "
            "factual only-use for rigor_and_feasibility.team_qualifications and "
            "rigor_and_feasibility.research_environment to ground expertise; "
            "do not invent facts beyond this block):\n"
            f"{external_researcher_context.strip()}\n"
        )
    web_ctx = ""
    if web_search_context and web_search_context.strip():
        web_ctx = (
            "\n\nWEB SEARCH NOTES (short bullets from a web search pass; "
            "may be incomplete; treat as hints with URLs where given; "
            "verify against proposal when scoring):\n"
            f"{web_search_context.strip()[:6000]}\n"
        )
    text = (proposal_text or "").strip()
    if len(text) > 120000:
        text = text[:120000] + "\n\n[TRUNCATED FOR LENGTH]"
    return (
        "Evaluate the following research proposal and return the structured JSON "
        'assessment with four top-level categories under "categories" (all scored), '
        "overall_summary, "
        "overall_rationale, overall_confidence, major_strengths, major_weaknesses, "
        "and fatal_flaws. In major_strengths and major_weaknesses, put the most "
        "important items first in each array (descending importance). Provide "
        "overall_rating and overall_score_numeric when you can; the server "
        "re-derives them from your per-item decisions (overall_score_numeric is "
        "1-5; defaults apply if missing or invalid).\n\n"
        "PROPOSAL TEXT:\n"
        f"{text}"
        f"{author}"
        f"{external}"
        f"{web_ctx}"
        f"{ctx}"
    )
