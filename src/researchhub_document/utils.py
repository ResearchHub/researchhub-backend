from datetime import datetime, timedelta

from django.core.cache import cache
from django.db.models.query import QuerySet

from paper.utils import add_default_hub, get_cache_key
from researchhub_document.related_models.constants.document_type import (
    ALL,
    HYPOTHESIS,
    PAPER,
    POSTS,
)
from researchhub_document.related_models.constants.filters import (
    AUTHOR_CLAIMED,
    DISCUSSED,
    NEWEST,
    OPEN_ACCESS,
    TOP,
    TRENDING,
)
from researchhub_document.tasks import preload_trending_documents
from utils.sentry import log_error

CACHE_TOP_RATED_DATES = (
    "-score_today",
    "-score_week",
    "-score_month",
    "-score_year",
    "-score_all_time",
)
CACHE_DATE_RANGES = ("today", "week", "month", "year", "all_time")
CACHE_DOCUMENT_TYPES = [
    "all",
    "paper",
    "posts",
    "hypothesis",
]


def get_cache_key(obj_type, pk):
    return f"{obj_type}_{pk}"


def add_default_hub(hub_ids):
    if 0 not in hub_ids:
        return [0] + list(hub_ids)
    return hub_ids


def get_doc_type_key(document):
    doc_type = document.document_type.lower()
    if doc_type == "discussion":
        return "posts"

    return doc_type


def get_date_ranges_by_time_scope(time_scope):
    end_date = datetime.now()
    if time_scope == "all_time":
        start_date = datetime(year=2018, month=12, day=31, hour=0)
    elif time_scope == "year":
        start_date = datetime.now() - timedelta(days=365)
    elif time_scope == "month":
        start_date = datetime.now() - timedelta(days=30)
    elif time_scope == "week":
        start_date = datetime.now() - timedelta(days=7)
    # Today
    else:
        # Given that our "today" results are minimal
        # it makes sense to have a bit of an extra buffer
        # for the forseeable future.
        hours_buffer = 10
        start_date = datetime.now() - timedelta(hours=(24 + hours_buffer))

    return (start_date, end_date)


def reset_unified_document_cache(
    hub_ids=[],
    document_type=[ALL.lower(), POSTS.lower(), PAPER.lower(), HYPOTHESIS.lower()],
    filters=[DISCUSSED, TRENDING, NEWEST, TOP, AUTHOR_CLAIMED, OPEN_ACCESS],
    date_ranges=CACHE_DATE_RANGES,
    with_default_hub=False,
):
    if isinstance(hub_ids, QuerySet):
        hub_ids = list(hub_ids)

    if with_default_hub and 0 not in hub_ids:
        hub_ids.append(0)
    elif with_default_hub is False and 0 in hub_ids:
        hub_ids.remove(0)

    for doc_type in document_type:
        for hub_id in hub_ids:
            for f in filters:
                for time_scope in date_ranges:
                    # Only homepage gets top priority
                    if hub_id == 0:
                        priority = 1
                    else:
                        priority = 3

                    preload_trending_documents.apply_async(
                        (
                            doc_type,
                            hub_id,
                            f,
                            time_scope,
                        ),
                        priority=priority,
                        countdown=1,
                    )


def update_unified_document_to_paper(paper):
    from researchhub_document.models import ResearchhubUnifiedDocument

    unified_doc = ResearchhubUnifiedDocument.objects.filter(paper__id=paper.id)
    if unified_doc.exists():
        try:
            rh_unified_doc = unified_doc.first()
            curr_score = paper.score()
            rh_unified_doc.score = curr_score
            hubs = paper.hubs.all()
            rh_unified_doc.hubs.add(*hubs)
            paper.calculate_hot_score()
            rh_unified_doc.save()
            reset_unified_document_cache(list(hubs.values_list("id", flat=True)))
        except Exception as e:
            print(e)
            log_error(e)


def invalidate_trending_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True,
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    "hub", f"{doc_type}_{hub_id}_-hot_score_{date_range}"
                )
                cache.delete(cache_key)


def invalidate_top_rated_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True,
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    "hub", f"{doc_type}_{hub_id}_-score_{date_range}"
                )
                cache.delete(cache_key)


def invalidate_newest_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True,
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    "hub", f"{doc_type}_{hub_id}_-created_date_{date_range}"
                )
                cache.delete(cache_key)


def invalidate_most_discussed_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True,
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    "hub", f"{doc_type}_{hub_id}_-discussed_{date_range}"
                )
                cache.delete(cache_key)
