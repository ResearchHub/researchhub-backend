import logging

from purchase.related_models.constants.currency import USD
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.rfp_email_context import _format_amount, _format_deadline

logger = logging.getLogger(__name__)


def get_proposal_frontend_url(post_or_unified_document) -> str | None:
    """
    Build frontend URL for a proposal (preregistration post).
    Accepts ResearchhubPost or ResearchhubUnifiedDocument.
    Preregistration pages: https://www.researchhub.com/fund/{id}/{slug}
    """
    if not post_or_unified_document:
        return None
    try:
        udoc = getattr(
            post_or_unified_document,
            "unified_document",
            post_or_unified_document,
        )
        if udoc and getattr(udoc, "frontend_view_link", None):
            return udoc.frontend_view_link()
        post = getattr(post_or_unified_document, "get_document", lambda: None)()
        if not post:
            post = post_or_unified_document
        post_id = getattr(post, "id", None)
        post_slug = getattr(post, "slug", None)
        if not post_id or not post_slug:
            return None
        return f"{BASE_FRONTEND_URL}/fund/{post_id}/{post_slug}"
    except Exception:
        logger.exception("get_proposal_frontend_url failed")
        return None


def _format_amount_raised(amount_usd: float | None) -> str:
    """Format amount raised (USD float) for display, e.g. $5K, $1.2K."""
    if amount_usd is None or amount_usd <= 0:
        return ""
    try:
        n = int(round(amount_usd))
        if n >= 1_000_000:
            return f"${n // 1_000_000}M"
        if n >= 1_000:
            return f"${n // 1_000}K"
        return f"${n}"
    except (TypeError, ValueError):
        return f"${amount_usd:.0f}" if amount_usd else ""


def _unified_document_for_proposal(post_or_unified_document):
    return getattr(
        post_or_unified_document,
        "unified_document",
        post_or_unified_document,
    )


def _resolve_post_for_proposal_context(post_or_unified_document, udoc):
    """Return the ResearchhubPost for context, or None."""
    if getattr(post_or_unified_document, "title", None) is not None:
        return post_or_unified_document
    if udoc:
        return udoc.get_document()
    return None


def _creator_display_name(created_by) -> str:
    if not created_by:
        return ""
    first = (getattr(created_by, "first_name", None) or "").strip()
    last = (getattr(created_by, "last_name", None) or "").strip()
    name = " ".join(p for p in [first, last] if p).strip()
    if name:
        return name
    return (getattr(created_by, "email", None) or "").strip()


def _fundraise_email_fields(udoc) -> dict:
    empty = {
        "goal_amount": "",
        "amount_raised": "",
        "contributor_count": "",
        "deadline": "",
    }
    if not udoc or not getattr(udoc, "fundraises", None):
        return empty
    fundraise = udoc.fundraises.first()
    if not fundraise:
        return empty

    summary = fundraise.get_contributors_summary()
    contributor_count = str(summary.total) if summary.total else ""
    return {
        "goal_amount": _format_amount(fundraise.goal_amount),
        "amount_raised": _format_amount_raised(
            fundraise.get_amount_raised(currency=USD)
        ),
        "contributor_count": contributor_count,
        "deadline": _format_deadline(fundraise.end_date),
    }


def build_proposal_context(
    post_or_unified_document, description_snippet_length: int = 500
) -> dict:
    """
    Build proposal (preregistration post) context dict for email templates.
    Accepts ResearchhubPost or ResearchhubUnifiedDocument (document_type PREREGISTRATION).
    Returns: title, url, created_by_name, goal_amount, amount_raised, contributor_count,
             deadline, blurb.

    Unexpected errors are logged at ERROR (with traceback) and an empty dict is returned
    so email generation can continue without proposal placeholders filled.
    """
    if not post_or_unified_document:
        return {}
    try:
        udoc = _unified_document_for_proposal(post_or_unified_document)
        post = _resolve_post_for_proposal_context(post_or_unified_document, udoc)
        if not post:
            return {}

        title = (getattr(post, "title", None) or "").strip()
        url = get_proposal_frontend_url(post_or_unified_document) or ""
        created_by_name = _creator_display_name(getattr(post, "created_by", None))

        raw_blurb = getattr(post, "renderable_text", None) or ""
        blurb = raw_blurb[:description_snippet_length].strip()

        fundraise_fields = _fundraise_email_fields(udoc)
        return {
            "title": title,
            "url": url,
            "created_by_name": created_by_name,
            **fundraise_fields,
            "blurb": blurb,
        }
    except Exception:
        logger.exception("build_proposal_context failed")
        return {}
