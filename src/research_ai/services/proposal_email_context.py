from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.rfp_email_context import _format_amount, _format_deadline


def get_proposal_frontend_url(post_or_unified_document) -> str | None:
    """
    Build frontend URL for a proposal (preregistration post).
    Accepts ResearchhubPost or ResearchhubUnifiedDocument.
    Preregistration pages: https://www.researchhub.com/post/{id}/{slug}
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
        return f"{BASE_FRONTEND_URL}/post/{post_id}/{post_slug}"
    except Exception:
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


def build_proposal_context(
    post_or_unified_document, description_snippet_length: int = 500
) -> dict:
    """
    Build proposal (preregistration post) context dict for email templates.
    Accepts ResearchhubPost or ResearchhubUnifiedDocument (document_type PREREGISTRATION).
    Returns: title, url, created_by_name, goal_amount, amount_raised, contributor_count,
             deadline, blurb.
    """
    if not post_or_unified_document:
        return {}
    try:
        udoc = getattr(
            post_or_unified_document,
            "unified_document",
            post_or_unified_document,
        )
        post = (
            post_or_unified_document
            if getattr(post_or_unified_document, "title", None) is not None
            else (udoc.get_document() if udoc else None)
        )
        if not post:
            return {}

        title = (getattr(post, "title", None) or "").strip()
        url = get_proposal_frontend_url(post_or_unified_document) or ""

        created_by = getattr(post, "created_by", None)
        created_by_name = ""
        if created_by:
            first = (getattr(created_by, "first_name", None) or "").strip()
            last = (getattr(created_by, "last_name", None) or "").strip()
            created_by_name = " ".join(p for p in [first, last] if p).strip()
            if not created_by_name:
                created_by_name = (getattr(created_by, "email", None) or "").strip()

        blurb = (getattr(post, "renderable_text", None) or "")[
            :description_snippet_length
        ]
        blurb = blurb.strip()

        goal_amount = ""
        amount_raised = ""
        contributor_count = ""
        deadline = ""

        fundraise = None
        if udoc and getattr(udoc, "fundraises", None):
            fundraise = udoc.fundraises.first()
        if fundraise:
            goal_amount = _format_amount(fundraise.goal_amount)
            from purchase.related_models.constants.currency import USD

            amount_raised = _format_amount_raised(
                fundraise.get_amount_raised(currency=USD)
            )
            summary = fundraise.get_contributors_summary()
            contributor_count = str(summary.total) if summary.total else ""
            deadline = _format_deadline(fundraise.end_date)

        return {
            "title": title,
            "url": url,
            "created_by_name": created_by_name,
            "goal_amount": goal_amount,
            "amount_raised": amount_raised,
            "contributor_count": contributor_count,
            "deadline": deadline,
            "blurb": blurb,
        }
    except Exception:
        return {}
