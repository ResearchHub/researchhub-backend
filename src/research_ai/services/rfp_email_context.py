import logging
from datetime import datetime
from decimal import Decimal

from research_ai.constants import BASE_FRONTEND_URL
from research_ai.models import Expert, ExpertSearch, SearchExpert
from research_ai.services.expert_display import expert_to_api_row

logger = logging.getLogger(__name__)


def get_grant_frontend_url(grant) -> str | None:
    """
    Build frontend URL for a Grant using the linked post's id and slug.
    Grant pages are routed by post: https://www.researchhub.com/grant/{post.id}/{post.slug}
    """
    if not grant or not grant.unified_document_id:
        return None
    try:
        post = grant.unified_document.posts.first()
        if not post:
            return None
        post_id = getattr(post, "id", None)
        post_slug = getattr(post, "slug", None)
        if not post_id or not post_slug:
            return None
        base = BASE_FRONTEND_URL
        return f"{base}/grant/{post_id}/{post_slug}"
    except Exception:
        logger.exception("get_grant_frontend_url failed")
        return None


def _format_amount(amount: Decimal | None) -> str:
    """Format grant amount for display, e.g. $5K, $200K."""
    if amount is None:
        return ""
    try:
        n = int(amount)
        if n >= 1_000_000:
            return f"${n // 1_000_000}M"
        if n >= 1_000:
            return f"${n // 1_000}K"
        return f"${n}"
    except (TypeError, ValueError):
        return str(amount) if amount else ""


def _format_deadline(end_date: datetime | None) -> str:
    """Format grant end_date for display."""
    if not end_date:
        return ""
    try:
        return end_date.strftime("%B %d, %Y")
    except Exception:
        return str(end_date) if end_date else ""


def build_rfp_context(grant, description_snippet_length: int = 500) -> dict:
    """
    Build RFP context dict from a Grant for email templates and prompts.
    Returns: amount, deadline, title, url, description_snippet, blurb.

    Unexpected errors are logged at ERROR (with traceback) and an empty dict is returned
    so email generation can continue without RFP placeholders filled.
    """
    if not grant:
        return {}
    try:
        doc = (
            grant.unified_document.get_document() if grant.unified_document_id else None
        )
        title = (
            (grant.short_title or "").strip()
            or (getattr(doc, "title", None) or "").strip()
            or ""
        )
        description = (grant.description or "")[:description_snippet_length]
        return {
            "amount": _format_amount(grant.amount),
            "deadline": _format_deadline(grant.end_date),
            "title": title,
            "url": get_grant_frontend_url(grant) or "",
            "description_snippet": description,
            "blurb": description,
        }
    except Exception:
        logger.exception("build_rfp_context failed")
        return {}


def get_expert_for_search_email(
    expert_search: ExpertSearch | None, expert_email: str
) -> Expert | None:
    """
    Return the Expert linked to this search for the given email (first match by position).
    """
    if not expert_search:
        return None
    email_norm = (expert_email or "").strip().lower()
    if not email_norm:
        return None
    se = (
        SearchExpert.objects.filter(
            expert_search=expert_search,
            expert__email__iexact=email_norm,
        )
        .select_related("expert")
        .order_by("position", "id")
        .first()
    )
    return se.expert if se else None


def resolve_expert_from_search(expert_search, expert_email: str) -> dict | None:
    """
    Get one expert dict from ExpertSearch results (SearchExpert + Expert) by email.

    Same structured fields as the expert API row, but without ``name`` (display name is
    derived in serializers via ``expert_to_api_row`` / ``build_expert_display_name``).
    """
    expert = get_expert_for_search_email(expert_search, expert_email)
    if not expert:
        return None
    row = expert_to_api_row(expert, expert_id=expert.id)
    row.pop("name", None)
    return row


def resolve_grant(*, expert_search: ExpertSearch | None = None):
    """
    Resolve a Grant from expert_search's unified_document.
    Returns Grant instance or None.
    """
    if not expert_search or not expert_search.unified_document_id:
        return None
    try:
        return expert_search.unified_document.grants.first()
    except Exception:
        logger.exception("resolve_grant failed")
        return None
