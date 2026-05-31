"""Read-only enrichment for the risk score events API."""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models import Count, Max, Min, Sum

from paper.related_models.paper_model import Paper
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import BountySolution
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models.review_model import Review
from user.related_models.risk_score_model import RiskScoreEvent

logger = logging.getLogger(__name__)

EventType = RiskScoreEvent.EventType

# Collapses related event types into a single moderator-facing bucket.
INSIGHT_GROUPS = {
    EventType.WORK_APPROVED: "WORKS_MODERATED",
    EventType.WORK_DECLINED: "WORKS_MODERATED",
    EventType.PERSONA_VERIFIED_WHITELISTED: "PERSONA_VERIFIED",
    EventType.PERSONA_VERIFIED_NON_WHITELISTED: "PERSONA_VERIFIED",
}


def _doc_title(doc):
    if doc is None:
        return ""
    if isinstance(doc, Paper):
        return doc.paper_title or doc.title or ""
    return getattr(doc, "title", "") or ""


_PATH_SEGMENTS = {
    "GRANT": "grant",
    "PREREGISTRATION": "proposal",
    "QUESTION": "post",
    "DISCUSSION": "post",
    "POSTS": "post",
    "BOUNTY": "post",
}


def _doc_url(unified_document, doc):
    """Build the frontend URL from cached `doc` (avoids a redundant DB query
    that `unified_document.frontend_view_link()` would otherwise trigger)."""
    if unified_document is None or doc is None:
        return None
    document_type = unified_document.document_type
    path_segment = _PATH_SEGMENTS.get(document_type, document_type.lower())
    return f"{BASE_FRONTEND_URL}/{path_segment}/{doc.id}/{doc.slug}"


def _doc_text(doc):
    if doc is None:
        return ""
    if isinstance(doc, Paper):
        return doc.abstract or ""
    return getattr(doc, "renderable_text", "") or ""


def _resolve_doc(unified_document):
    """Return (doc, document_type) without calling get_document twice."""
    if unified_document is None:
        return None, None
    return unified_document.get_document(), unified_document.document_type


def _detail(title, text, url, *, comment_type=None, document_type=None):
    return {
        "title": title or "",
        "text": text or "",
        "url": url,
        "comment_type": comment_type,
        "document_type": document_type,
    }


def _grant_detail(grant):
    unified_document = grant.unified_document
    doc, document_type = _resolve_doc(unified_document)
    return _detail(
        _doc_title(doc) or grant.short_title or grant.organization,
        grant.description,
        _doc_url(unified_document, doc),
        document_type=document_type,
    )


def _post_detail(post):
    unified_document = post.unified_document
    doc, document_type = _resolve_doc(unified_document)
    return _detail(
        post.title,
        post.renderable_text,
        _doc_url(unified_document, doc),
        document_type=document_type,
    )


def _comment_detail(comment):
    unified_document = comment.unified_document
    doc, document_type = _resolve_doc(unified_document)
    base_url = _doc_url(unified_document, doc)
    return _detail(
        _doc_title(doc),
        comment.plain_text,
        f"{base_url}#comment-{comment.id}" if base_url else None,
        comment_type=comment.comment_type,
        document_type=document_type,
    )


def _unified_document_detail(unified_document):
    doc, document_type = _resolve_doc(unified_document)
    return _detail(
        _doc_title(doc),
        _doc_text(doc),
        _doc_url(unified_document, doc),
        document_type=document_type,
    )


def _bounty_solution_detail(solution):
    if isinstance(solution.item, RhCommentModel):
        return _comment_detail(solution.item)
    logger.warning(
        "BountySolution %s has non-comment item; no risk score detail available",
        solution.pk,
    )
    return None


def _purchase_detail(purchase):
    if isinstance(purchase.item, RhCommentModel):
        return _comment_detail(purchase.item)
    logger.warning(
        "Purchase %s has non-comment item; no risk score detail available",
        purchase.pk,
    )
    return None


def _review_detail(review):
    if isinstance(review.item, RhCommentModel):
        return _comment_detail(review.item)
    logger.warning(
        "Review %s has non-comment item; no risk score detail available",
        review.pk,
    )
    return None


SOURCE_DETAIL_BUILDERS = {
    Grant: _grant_detail,
    ResearchhubPost: _post_detail,
    RhCommentModel: _comment_detail,
    ResearchhubUnifiedDocument: _unified_document_detail,
    BountySolution: _bounty_solution_detail,
    Purchase: _purchase_detail,
    Review: _review_detail,
}

# Per-model FK hints applied when batch-loading sources. Keeps subsequent
# attribute access (e.g. `comment.thread`) from triggering N+1 queries.
SOURCE_SELECT_RELATED = {
    RhCommentModel: ("thread",),
    Grant: ("unified_document",),
    ResearchhubPost: ("unified_document",),
    BountySolution: ("bounty",),
    Review: ("unified_document",),
}


def _fetch_sources(model, ids):
    manager = getattr(model, "all_objects", model.objects)
    qs = manager.filter(pk__in=ids)
    related = SOURCE_SELECT_RELATED.get(model)
    return qs.select_related(*related) if related else qs


def _build_detail(source):
    if source is None:
        return None
    builder = SOURCE_DETAIL_BUILDERS.get(type(source))
    return builder(source) if builder else None


def build_event_details(events):
    """Map event id to a detail payload (or None for sourceless events)."""
    events = list(events)
    ids_by_ct = {}
    for event in events:
        if event.source_content_type_id and event.source_content_id:
            ids_by_ct.setdefault(event.source_content_type_id, []).append(
                event.source_content_id
            )

    sources = {}
    for ct_id, obj_ids in ids_by_ct.items():
        model = ContentType.objects.get_for_id(ct_id).model_class()
        if model is None or model not in SOURCE_DETAIL_BUILDERS:
            continue
        for obj in _fetch_sources(model, obj_ids):
            sources[(ct_id, obj.pk)] = obj

    return {
        event.id: _build_detail(
            sources.get((event.source_content_type_id, event.source_content_id))
        )
        for event in events
    }


def build_insights(user):
    """Aggregate per-event-type counts and sentiment for a user."""
    aggregates = (
        RiskScoreEvent.objects.filter(user=user)
        .values("event_type")
        .annotate(
            count=Count("id"),
            total_delta=Sum("delta"),
            min_delta=Min("delta"),
            max_delta=Max("delta"),
        )
    )

    buckets = {}
    for agg in aggregates:
        key = INSIGHT_GROUPS.get(agg["event_type"], agg["event_type"])
        if key not in buckets:
            buckets[key] = {
                "count": 0,
                "total_delta": 0,
                "min_delta": agg["min_delta"],
                "max_delta": agg["max_delta"],
            }
        bucket = buckets[key]
        bucket["count"] += agg["count"]
        bucket["total_delta"] += agg["total_delta"]
        bucket["min_delta"] = min(bucket["min_delta"], agg["min_delta"])
        bucket["max_delta"] = max(bucket["max_delta"], agg["max_delta"])

    return [
        {
            "event_type": key,
            "count": bucket["count"],
            "total_delta": bucket["total_delta"],
            "min_delta": bucket["min_delta"],
            "max_delta": bucket["max_delta"],
        }
        for key, bucket in sorted(buckets.items())
    ]
