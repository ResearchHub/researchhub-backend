import logging
from dataclasses import dataclass

from research_ai.models import ExpertSearch
from research_ai.services.proposal_email_context import build_proposal_context
from research_ai.services.rfp_email_context import build_rfp_context, resolve_grant
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

logger = logging.getLogger(__name__)

_SNIPPET_LEN = 500


@dataclass(frozen=True)
class ExpertSearchEmailDocumentContext:
    """
    For LLM prompts: at most one branch is typically populated.
    Grant / preregistration use structured RFP or proposal dicts.
    Paper uses title + abstract. All other linked doc types share one generic snippet.
    user_additional_context: optional notes from ExpertSearch.additional_context.
    """

    rfp_context_dict: dict | None
    proposal_context_dict: dict | None
    generic_work_context_dict: dict | None
    user_additional_context: str = ""


def _fallback_from_expert_search(expert_search: ExpertSearch | None) -> dict:
    if not expert_search:
        return {}
    title = (getattr(expert_search, "name", None) or "").strip()
    query = (getattr(expert_search, "query", None) or "").strip()
    if not title and query:
        title = query[:200].strip() + ("…" if len(query) > 200 else "")
    blurb = query[:_SNIPPET_LEN] if query else ""
    return {
        "title": title,
        "url": "",
        "blurb": blurb.strip(),
        "kind": "custom_query",
    }


def _safe_get_document(udoc: ResearchhubUnifiedDocument):
    try:
        return udoc.get_document()
    except Exception:
        logger.debug("get_document failed for udoc id=%s", udoc.id, exc_info=True)
        try:
            return udoc.posts.first()
        except Exception:
            return None


def _build_paper_generic(udoc: ResearchhubUnifiedDocument) -> dict:
    try:
        paper = getattr(udoc, "paper", None)
        if not paper:
            return {}
        title = (getattr(paper, "title", None) or "").strip()
        abstract = (getattr(paper, "abstract", None) or "").strip()
        blurb = abstract[:_SNIPPET_LEN] if abstract else ""
        try:
            url = udoc.frontend_view_link() or ""
        except Exception:
            logger.exception("paper frontend_view_link failed")
            url = ""
        return {
            "title": title,
            "url": url,
            "blurb": blurb.strip(),
            "kind": "paper",
        }
    except Exception:
        logger.exception("build_paper_generic failed")
        return {}


def _build_generic_linked_document(udoc: ResearchhubUnifiedDocument) -> dict:
    """
    Title, text snippet, and URL for any non-paper linked unified doc
    (discussion, post, note, etc. — no per-type LLM framing).
    """
    doc = _safe_get_document(udoc)
    if not doc:
        return {}
    try:
        title = (getattr(doc, "title", None) or "").strip()
        raw_blurb = (
            getattr(doc, "renderable_text", None) or getattr(doc, "text", None) or ""
        )
        if not isinstance(raw_blurb, str):
            raw_blurb = str(raw_blurb or "")
        blurb = raw_blurb[:_SNIPPET_LEN].strip()
        try:
            url = udoc.frontend_view_link() or ""
        except Exception:
            logger.exception("generic linked doc frontend_view_link failed")
            url = ""
        return {
            "title": title,
            "url": url,
            "blurb": blurb,
            "kind": "generic",
        }
    except Exception:
        logger.exception("build_generic_linked_document failed")
        return {}


def _nonempty_generic(d: dict) -> dict | None:
    if d and (d.get("title") or d.get("blurb")):
        return d
    return None


def _user_additional_context_from_search(expert_search: ExpertSearch | None) -> str:
    if not expert_search:
        return ""
    raw = getattr(expert_search, "additional_context", None)
    if raw is None or not isinstance(raw, str):
        return ""
    return raw.strip()


def resolve_expert_search_email_document_context(
    expert_search: ExpertSearch | None,
) -> ExpertSearchEmailDocumentContext:
    """
    GRANT -> rfp dict. PREREGISTRATION -> proposal dict. PAPER -> paper generic dict.
    Any other linked document type -> one shared generic snippet; no document -> search fallback.
    """
    extra = _user_additional_context_from_search(expert_search)

    if not expert_search or not expert_search.unified_document_id:
        fb = _fallback_from_expert_search(expert_search)
        return ExpertSearchEmailDocumentContext(
            None, None, _nonempty_generic(fb), extra
        )

    udoc = expert_search.unified_document
    dtype = udoc.document_type

    if dtype == GRANT:
        grant = resolve_grant(expert_search=expert_search)
        rfp_d = build_rfp_context(grant) if grant else None
        if rfp_d and (rfp_d.get("title") or rfp_d.get("blurb")):
            return ExpertSearchEmailDocumentContext(rfp_d, None, None, extra)
        fb = _fallback_from_expert_search(expert_search)
        return ExpertSearchEmailDocumentContext(
            None, None, _nonempty_generic(fb), extra
        )

    if dtype == PREREGISTRATION:
        proposal_d = build_proposal_context(udoc) or build_proposal_context(
            _safe_get_document(udoc)
        )
        if proposal_d and (proposal_d.get("title") or proposal_d.get("blurb")):
            return ExpertSearchEmailDocumentContext(None, proposal_d, None, extra)
        fb = _fallback_from_expert_search(expert_search)
        return ExpertSearchEmailDocumentContext(
            None, None, _nonempty_generic(fb), extra
        )

    if dtype == PAPER:
        g = _build_paper_generic(udoc)
        if _nonempty_generic(g):
            return ExpertSearchEmailDocumentContext(None, None, g, extra)
        fb = _fallback_from_expert_search(expert_search)
        return ExpertSearchEmailDocumentContext(
            None, None, _nonempty_generic(fb), extra
        )

    g = _build_generic_linked_document(udoc)
    if _nonempty_generic(g):
        return ExpertSearchEmailDocumentContext(None, None, g, extra)
    fb = _fallback_from_expert_search(expert_search)
    return ExpertSearchEmailDocumentContext(None, None, _nonempty_generic(fb), extra)


def _format_grant_narrative(r: dict) -> str:
    parts = [
        "This outreach relates to a grant or funding opportunity (RFP).",
        f"The opportunity is titled: {r.get('title') or 'N/A'}.",
    ]
    if r.get("amount"):
        parts.append(f"Indicative amount or scale: {r['amount']}.")
    if r.get("deadline"):
        parts.append(f"Relevant deadline: {r['deadline']}.")
    if r.get("blurb"):
        parts.append(f"Summary for context: {r['blurb']}")
    if r.get("url"):
        parts.append(f"More information: {r['url']}")
    return "\n".join(parts)


def _format_proposal_narrative(p: dict) -> str:
    parts = [
        "This outreach relates to a preregistration, proposal, or crowdfunding-style "
        "funding post on ResearchHub.",
        f"Title: {p.get('title') or 'N/A'}.",
    ]
    if p.get("created_by_name"):
        parts.append(f"Listed creator / organizer: {p['created_by_name']}.")
    if p.get("goal_amount"):
        parts.append(f"Funding goal: {p['goal_amount']}.")
    if p.get("amount_raised"):
        parts.append(f"Amount raised so far: {p['amount_raised']}.")
    if p.get("contributor_count"):
        parts.append(f"Contributor count: {p['contributor_count']}.")
    if p.get("deadline"):
        parts.append(f"Deadline: {p['deadline']}.")
    if p.get("blurb"):
        parts.append(f"Description snippet: {p['blurb']}")
    if p.get("url"):
        parts.append(f"Link: {p['url']}")
    return "\n".join(parts)


def _format_generic_work_narrative(g: dict) -> str:
    kind = (g.get("kind") or "work").replace("_", " ")
    if kind == "paper":
        lead = "This expert search is grounded in the following research paper."
    elif kind == "custom query":
        lead = (
            "This expert search is based on a free-text or uploaded query "
            "(no single linked document)."
        )
    elif kind == "generic":
        lead = (
            "This expert search is tied to a linked ResearchHub document "
            "(not a grant, preregistration, or paper)."
        )
    else:
        lead = f"This expert search is tied to a ResearchHub post or document ({kind})."
    parts = [lead]
    if g.get("title"):
        parts.append(f"Title: {g['title']}.")
    if g.get("blurb"):
        parts.append(f"Summary / abstract / excerpt: {g['blurb']}")
    if g.get("url"):
        parts.append(f"Link: {g['url']}")
    return "\n".join(parts)


def format_document_context_for_llm(ctx: ExpertSearchEmailDocumentContext) -> str:
    """Plain-language block for the LLM (replaces old template outreach_context)."""
    if ctx.rfp_context_dict:
        base = _format_grant_narrative(ctx.rfp_context_dict)
    elif ctx.proposal_context_dict:
        base = _format_proposal_narrative(ctx.proposal_context_dict)
    elif ctx.generic_work_context_dict:
        base = _format_generic_work_narrative(ctx.generic_work_context_dict)
    else:
        base = ""
    extra = (ctx.user_additional_context or "").strip()
    if not extra:
        return base
    guidance = (
        "The requester provided additional guidance when running this expert search:\n"
        f"{extra}"
    )
    if base:
        return f"{base}\n\n{guidance}"
    return guidance
