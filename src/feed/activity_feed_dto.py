from django.core.files.storage import default_storage
from django.utils.html import strip_tags

from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import EscrowRecipients
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    PEER_REVIEW,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
)
from user.related_models.funding_activity_model import FundingActivity


def _serialize_hub(hub) -> dict | None:
    if hub is None:
        return None
    return {"id": hub.id, "name": hub.name, "slug": hub.slug}


def _strip_title(title: str | None) -> str | None:
    if title is None:
        return None
    return strip_tags(title).strip() or None


def _get_post_image_url(post) -> str | None:
    if not post or not post.image:
        return None
    return default_storage.url(post.image)


def _get_paper_image_url(paper) -> str | None:
    if not paper:
        return None
    try:
        primary_figure = paper.figures.filter(is_primary=True).first()
        if not primary_figure or not primary_figure.file:
            return None
        return primary_figure.file.url
    except Exception:
        return None


def _build_fundraise_subset(fundraise: Fundraise) -> dict:
    usd_goal = float(fundraise.goal_amount)
    try:
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
    except AttributeError:
        rsc_goal = None

    end_date = None
    if fundraise.status == Fundraise.OPEN:
        end_date = fundraise.end_date

    return {
        "status": fundraise.status,
        "goal_currency": fundraise.goal_currency,
        "goal_amount": {"usd": usd_goal, "rsc": rsc_goal},
        "amount_raised": {
            "usd": fundraise.get_amount_raised(currency=USD),
            "rsc": fundraise.get_amount_raised(currency=RSC),
        },
        "end_date": end_date,
    }


def _get_fundraise_for_unified_document(unified_document):
    if not hasattr(unified_document, "fundraises"):
        return None
    fundraises = unified_document.fundraises.all()
    if not fundraises:
        return None
    return fundraises[0]


def _build_grant_subset(grant: Grant) -> dict:
    num_applicants = getattr(grant, "num_applicants", None)
    if num_applicants is None:
        num_applicants = grant.applications.count()

    end_date = None
    if grant.status == Grant.OPEN:
        end_date = grant.end_date

    return {
        "id": grant.id,
        "status": grant.status,
        "organization": grant.organization,
        "amount": str(grant.amount),
        "currency": grant.currency,
        "end_date": end_date,
        "num_applicants": num_applicants,
    }


def _get_grant_for_unified_document(unified_document):
    if not hasattr(unified_document, "grants"):
        return None
    grants = unified_document.grants.all()
    if not grants:
        return None
    return grants[0]


def build_related_work(unified_document) -> dict | None:
    """
    Minimum document payload for activity card image + title + link + hub.
    """
    if unified_document is None:
        return None

    document_type = unified_document.document_type
    try:
        document = unified_document.get_document()
    except Exception:
        document = None

    if document is None:
        return None

    hub = unified_document.get_primary_hub(fallback=True)
    hub_data = _serialize_hub(hub)

    fundraise_data = None
    grant_data = None

    if document_type == PREREGISTRATION:
        fundraise = _get_fundraise_for_unified_document(unified_document)
        if fundraise:
            fundraise_data = _build_fundraise_subset(fundraise)

    if document_type == GRANT:
        grant = _get_grant_for_unified_document(unified_document)
        if grant:
            grant_data = _build_grant_subset(grant)

    if document_type == PAPER:
        title = _strip_title(getattr(document, "display_title", None) or document.title)
        return {
            "id": document.id,
            "slug": document.slug,
            "unified_document_id": unified_document.id,
            "document_type": document_type,
            "title": title,
            "image_url": _get_paper_image_url(document),
            "hub": hub_data,
            "fundraise": None,
            "grant": None,
        }

    # Post-backed document types
    title = _strip_title(document.title)
    return {
        "id": document.id,
        "slug": document.slug,
        "unified_document_id": unified_document.id,
        "document_type": document_type,
        "title": title,
        "image_url": _get_post_image_url(document),
        "hub": hub_data,
        "fundraise": fundraise_data,
        "grant": grant_data,
    }


def serialize_activity_bounty(bounty: Bounty) -> dict:
    expiration_date = None
    if bounty.status == Bounty.OPEN:
        expiration_date = bounty.expiration_date

    return {
        "id": bounty.id,
        "amount": str(bounty.amount),
        "bounty_type": bounty.bounty_type,
        "status": bounty.status,
        "expiration_date": expiration_date,
    }


def resolve_activity_bounty(feed_entry, item=None) -> dict | None:
    if feed_entry.content_type.model != "rhcommentmodel":
        return None

    comment = item or feed_entry.item
    if comment is None:
        return None

    bounty = comment.bounties.filter(parent__isnull=True).first()
    if bounty is None:
        return None

    return serialize_activity_bounty(bounty)


def resolve_bounty_id_for_funding_activity(activity: FundingActivity) -> int | None:
    if activity.source_type != FundingActivity.BOUNTY_PAYOUT:
        return None

    source = getattr(activity, "_prefetched_bounty_payout_source", None)
    if source is None:
        source = activity.source
    if not isinstance(source, EscrowRecipients):
        return None

    escrow = source.escrow
    bounty = (
        escrow.bounties.filter(bounty_type=Bounty.Type.REVIEW)
        .select_related("unified_document")
        .first()
    )
    return bounty.id if bounty else None


def resolve_activity_context(feed_entry, item=None) -> str | None:
    model = feed_entry.content_type.model
    item = item or feed_entry.item
    unified_document = feed_entry.unified_document

    if model == "fundingactivity" and item is not None:
        if item.source_type == FundingActivity.TIP_REVIEW:
            return "tip_review"
        if item.source_type == FundingActivity.BOUNTY_PAYOUT:
            return "bounty_payout"
        return None

    if model in ("purchase", "usdfundraisecontribution"):
        return "fundraise_contribution"

    if model == "rhcommentmodel" and item is not None:
        if item.bounties.filter(parent__isnull=True).exists():
            return "bounty_opened"
        if item.comment_type in (PEER_REVIEW, COMMUNITY_REVIEW):
            return "peer_review_published"
        return "comment_published"

    if model == "researchhubpost" and item is not None:
        doc_type = item.document_type
        if doc_type == GRANT:
            return "grant_opened"
        if doc_type == PREREGISTRATION:
            return "proposal_submitted"
        return "post_published"

    if model == "paper":
        return "paper_published"

    if model == "bounty":
        return "bounty_contributed"

    if unified_document is not None:
        doc_type = unified_document.document_type
        if doc_type == GRANT:
            return "grant_opened"
        if doc_type == PREREGISTRATION:
            return "proposal_submitted"
        if doc_type == PAPER:
            return "paper_published"

    return None
