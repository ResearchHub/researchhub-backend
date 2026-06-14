from django.core.files.storage import default_storage

from purchase.related_models.constants.currency import RSC, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PAPER,
    PREREGISTRATION,
)


def _get_post_image_url(post):
    if not post or not post.image:
        return None
    return default_storage.url(post.image)


def _get_paper_image_url(paper):
    try:
        primary_figure = paper.figures.filter(is_primary=True).first()
        if primary_figure and primary_figure.file:
            return primary_figure.file.url
    except Exception:
        pass

    if not paper.unified_document:
        return None

    journal_hub = paper.unified_document.get_journal()
    if journal_hub and journal_hub.hub_image:
        try:
            return journal_hub.hub_image.url
        except Exception:
            pass

    primary_hub = paper.unified_document.get_primary_hub()
    if primary_hub and primary_hub.hub_image:
        try:
            return primary_hub.hub_image.url
        except Exception:
            pass

    return None


def _serialize_slim_fundraise_for_related_work(fundraise):
    usd_goal = float(fundraise.goal_amount)
    try:
        rsc_goal = RscExchangeRate.usd_to_rsc(usd_goal)
    except AttributeError:
        rsc_goal = None

    return {
        "status": fundraise.status,
        "goal_amount": {"usd": usd_goal, "rsc": rsc_goal},
        "amount_raised": {
            "usd": fundraise.get_amount_raised(currency=USD),
            "rsc": fundraise.get_amount_raised(currency=RSC),
        },
        "start_date": fundraise.start_date,
        "end_date": fundraise.end_date,
    }


def _first_prefetched(relation):
    items = list(relation.all())
    return items[0] if items else None


def _serialize_grant_nested(grant):
    from feed.feed_list_dto import _grant_amount

    num_applicants = getattr(grant, "num_applicants", None)
    if num_applicants is None:
        num_applicants = grant.applications.count()

    return {
        "status": grant.status,
        "amount": _grant_amount(grant),
        "organization": grant.organization,
        "application_count": num_applicants,
    }


def _get_created_by(author_profile):
    if not author_profile:
        return None

    from feed.feed_list_dto import SlimAuthorSerializer

    return SlimAuthorSerializer(author_profile).data


def _build_common_fields_from_post(post, unified_document):
    author_profile = None
    if post.created_by:
        author_profile = getattr(post.created_by, "author_profile", None)

    return {
        "document_type": unified_document.document_type,
        "unified_document_id": unified_document.id,
        "id": post.id,
        "slug": post.slug,
        "title": post.title,
        "image_url": _get_post_image_url(post),
        "created_date": post.created_date,
        "created_by": _get_created_by(author_profile),
    }


def _build_common_fields_from_paper(paper, unified_document):
    from feed.serializers import SimpleAuthorSerializer

    uploaded_by = paper.uploaded_by
    author_profile = (
        getattr(uploaded_by, "author_profile", None) if uploaded_by else None
    )

    data = {
        "document_type": unified_document.document_type,
        "unified_document_id": unified_document.id,
        "id": paper.id,
        "slug": paper.slug or None,
        "title": paper.title or paper.paper_title,
        "image_url": _get_paper_image_url(paper),
        "created_date": paper.created_date,
        "created_by": _get_created_by(author_profile),
    }

    authors = paper.authors.all()
    if authors:
        data["authors"] = SimpleAuthorSerializer(authors, many=True).data

    return data


def _serialize_related_work_impl(unified_document):
    document_type = unified_document.document_type

    if document_type == PAPER:
        paper = getattr(unified_document, "paper", None)
        if not paper:
            return None
        return _build_common_fields_from_paper(paper, unified_document)

    post = (
        _first_prefetched(unified_document.posts)
        if hasattr(unified_document, "posts")
        else None
    )
    if not post:
        return None

    data = _build_common_fields_from_post(post, unified_document)

    if document_type == GRANT:
        grant = (
            _first_prefetched(unified_document.grants)
            if hasattr(unified_document, "grants")
            else None
        )
        if grant:
            data["grant"] = _serialize_grant_nested(grant)
    elif document_type == PREREGISTRATION:
        fundraise = (
            _first_prefetched(unified_document.fundraises)
            if hasattr(unified_document, "fundraises")
            else None
        )
        if fundraise:
            data["fundraise"] = _serialize_slim_fundraise_for_related_work(fundraise)

    return data


def serialize_related_work(unified_document, context=None):
    if unified_document is None:
        return None

    if context is not None:
        cache = context.setdefault("related_work_cache", {})
        cache_key = unified_document.id
        if cache_key in cache:
            return cache[cache_key]
        result = _serialize_related_work_impl(unified_document)
        cache[cache_key] = result
        return result

    return _serialize_related_work_impl(unified_document)
