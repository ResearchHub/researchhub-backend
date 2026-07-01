"""Prompt builders for the proposal draft agent.

Thin builders that compose the system and user prompts from shared ``.txt``
templates (see ``_loader``). The system prompt is static (the rubric, the
writing-voice rules, the grounding and iterate contracts); the user prompt is
seeded per run from the ``Expert`` profile and the RFP context so the agent
starts grounded before it calls a single tool.
"""

from research_ai.prompts._loader import load_template

# Profile works surfaced in the user-prompt seed (the agent can pull the full
# profile via get_researcher_profile).
_MAX_SEED_WORKS = 5

# Per-work abstract is trimmed in the seed so several works stay readable at a
# glance; the full abstract is always available via get_researcher_profile.
_MAX_SEED_ABSTRACT_CHARS = 600


def build_proposal_system_prompt(panel_threshold: float = 4.0) -> str:
    """The system prompt: rubric, voice rules, grounding + iterate contract.

    ``panel_threshold`` is substituted into the rubric so the agent drafts toward
    the same overall bar the gate enforces; pass the runner's configured value so
    the prompt never drifts from the gate.
    """
    threshold = f"{panel_threshold:g}"
    return load_template("proposal_draft_system.txt").replace(
        "{{PANEL_THRESHOLD}}", threshold
    )


def _render_resolution_lines(resolution: dict) -> list[str]:
    """Header lines naming the resolved researcher and their OpenAlex id."""
    lines: list[str] = []
    name = str(resolution.get("display_name") or "").strip()
    if name:
        lines.append(f"Resolved researcher: {name}")
    author_id = resolution.get("openalex_author_id")
    if author_id:
        lines.append(f"OpenAlex author id: {author_id}")
    return lines


def _trim_abstract(abstract: str) -> str:
    """Trim a work abstract to the seed length, keeping it readable at a glance."""
    if len(abstract) > _MAX_SEED_ABSTRACT_CHARS:
        return abstract[:_MAX_SEED_ABSTRACT_CHARS].rstrip() + "..."
    return abstract


def _render_work_lines(work: dict) -> list[str]:
    """Title/year/url line for a single work, plus its trimmed abstract."""
    title = str(work.get("title") or "").strip() or "(untitled)"
    year = str(work.get("publication_year") or "").strip()
    url = str(work.get("source_url") or "").strip()
    suffix = f" ({year})" if year else ""
    ref = f" -- {url}" if url else ""
    lines = [f"- {title}{suffix}{ref}"]
    abstract = str(work.get("abstract") or "").strip()
    if abstract:
        lines.append(f"    Abstract: {_trim_abstract(abstract)}")
    return lines


def _render_works_lines(works: list[dict]) -> list[str]:
    """The selected-works block, or a prompt to ground them when none are on file."""
    if not works:
        return [
            "No works are on file for this researcher; resolve and ground them "
            "with the OpenAlex tools before relying on any track record."
        ]
    lines = ["Selected works (the real track record to build on):"]
    for work in works[:_MAX_SEED_WORKS]:
        lines.extend(_render_work_lines(work))
    return lines


def _render_profile_summary(profile: dict | None) -> str:
    """Compact, readable summary of the persisted researcher profile."""
    profile = profile or {}
    works = [w for w in (profile.get("works") or []) if isinstance(w, dict)]
    lines = _render_resolution_lines(profile.get("resolution") or {})
    lines.extend(_render_works_lines(works))
    return "\n".join(lines)


def _render_rfp_summary(rfp_ctx: dict | None) -> str:
    """Compact summary of the RFP context dict from ``get_rfp_context``."""
    rfp_ctx = rfp_ctx or {}
    if rfp_ctx.get("error"):
        return f"RFP context unavailable: {rfp_ctx['error']}"
    lines: list[str] = []
    for label, key in (
        ("Funder", "organization"),
        ("Call", "short_title"),
        ("Budget", "amount"),
        ("Currency", "currency"),
        ("Deadline", "end_date"),
    ):
        value = str(rfp_ctx.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    rfp_text = str(rfp_ctx.get("rfp_text") or "").strip()
    if rfp_text:
        lines.append("\nRFP call text:\n" + rfp_text)
    return "\n".join(lines)


def build_proposal_user_prompt(expert, rfp_ctx: dict | None) -> str:
    """Seed the run from the ``Expert`` profile and the RFP context.

    The agent still has ``get_researcher_profile`` / ``get_rfp_context`` for the
    full, authoritative data; this is the head start so it does not draft blind.
    """
    profile_summary = _render_profile_summary(getattr(expert, "profile", None))
    rfp_summary = _render_rfp_summary(rfp_ctx)
    name = (getattr(expert, "full_name", "") or "").strip() or "this researcher"
    return (
        f"Draft a grant proposal for {name} in response to the RFP below.\n\n"
        "## Researcher profile\n"
        f"{profile_summary}\n\n"
        "## RFP\n"
        f"{rfp_summary}\n\n"
        "Begin by confirming the RFP and profile with the tools, then draft, "
        "judge, verify, revise, and submit per your instructions. The structured "
        "payload you submit must follow the submit_proposal contract exactly."
    )
