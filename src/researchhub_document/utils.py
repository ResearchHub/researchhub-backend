from researchhub_document.tasks import (
    preload_trending_documents,
    preload_hub_documents
)
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    POSTS,
    HYPOTHESIS,
    ALL,
)
from utils.sentry import log_error
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    TRENDING,
    NEWEST,
    TOP
)
from paper.utils import (
    get_cache_key,
    add_default_hub
)
from django.core.cache import cache

CACHE_TOP_RATED_DATES = (
    '-score_today',
    '-score_week',
    '-score_month',
    '-score_year',
    '-score_all_time'
)
CACHE_DATE_RANGES = (
    'today',
    'week',
    'month',
    'year',
    'all_time'
)
CACHE_DOCUMENT_TYPES = [
    'all',
    'paper',
    'posts',
    'hypothesis',
]

def get_cache_key(obj_type, pk):
    return f'{obj_type}_{pk}'


def add_default_hub(hub_ids):
    if 0 not in hub_ids:
        return [0] + list(hub_ids)
    return hub_ids

def get_date_range_key(start_date, end_date):
    time_difference = end_date - start_date

    if time_difference.days > 365:
        return "all_time"
    elif time_difference.days == 365:
        return "year"
    elif time_difference.days == 30 or time_difference.days == 31:
        return "month"
    elif time_difference.days == 7:
        return "week"
    else:
        return "today"

def get_doc_type_key(document):
    doc_type = document.document_type.lower()
    if doc_type == 'discussion':
        return 'posts'

    return doc_type

def reset_unified_document_cache(
    hub_ids,
    document_type=[
        ALL.lower(),
        POSTS.lower(),
        PAPER.lower(),
        HYPOTHESIS.lower()
    ],
    filters=[
        DISCUSSED,
        TRENDING,
        NEWEST,
        TOP
    ],
    date_ranges=CACHE_DATE_RANGES,
    use_celery=True
):

    for doc_type in document_type:
        for hub_id in hub_ids:
            for f in filters:
                for time_scope in date_ranges:
                    if use_celery:
                        preload_trending_documents.apply_async(
                            (
                                doc_type,
                                hub_id,
                                f,
                                time_scope,
                            ),
                            priority=1,
                            countdown=1
                        )
                    else:
                        preload_trending_documents(
                            doc_type,
                            hub_id,
                            f,
                            time_scope
                        )
        if use_celery:
            preload_hub_documents.apply_async(
                (doc_type, hub_ids),
                priority=1,
                countdown=1
            )
        else:
            preload_hub_documents(doc_type, hub_ids)


def update_unified_document_to_paper(paper):
    from researchhub_document.models import ResearchhubUnifiedDocument
    unified_doc = ResearchhubUnifiedDocument.objects.filter(
        paper__id=paper.id
    )
    if unified_doc.exists():
        try:
            rh_unified_doc = unified_doc.first()
            curr_score = paper.calculate_score()
            rh_unified_doc.score = curr_score
            hubs = paper.hubs.all()
            rh_unified_doc.hubs.add(*hubs)
            paper.calculate_hot_score()
            rh_unified_doc.save()
            reset_unified_document_cache(
                [0] + list(hubs.values_list('id', flat=True))
            )
        except Exception as e:
            print(e)
            log_error(e)

def invalidate_trending_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    'hub',
                    f'{doc_type}_{hub_id}_-hot_score_{date_range}'
                )
                cache.delete(cache_key)


def invalidate_top_rated_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    'hub',
                    f'{doc_type}_{hub_id}_-score_{date_range}'
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
                    'hub',
                    f'{doc_type}_{hub_id}_-created_date_{date_range}'
                )
                cache.delete(cache_key)


def invalidate_most_discussed_cache(
    hub_ids,
    document_types=CACHE_DOCUMENT_TYPES,
    date_ranges=CACHE_DATE_RANGES,
    with_default=True
):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for date_range in date_ranges:
            for doc_type in document_types:
                cache_key = get_cache_key(
                    'hub',
                    f'{doc_type}_{hub_id}_-discussed_{date_range}'
                )
                cache.delete(cache_key)
