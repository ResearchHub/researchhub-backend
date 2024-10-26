from datetime import datetime, timedelta

from django.db.models.query import QuerySet

from researchhub_document.related_models.constants.document_type import (
    ALL,
    BOUNTY,
    PAPER,
    POSTS,
    PREREGISTRATION,
    QUESTION,
)
from researchhub_document.related_models.constants.filters import (
    DISCUSSED,
    EXPIRING_SOON,
    HOT,
    MOST_RSC,
    NEW,
    UPVOTED,
)
from researchhub_document.tasks import preload_trending_documents
from utils.sentry import log_error

CACHE_DATE_RANGES = ("today", "week", "month", "year", "all")
CACHE_DOCUMENT_TYPES = [
    "all",
    "paper",
    "posts",
]


def get_doc_type_key(document):
    doc_type = document.document_type.lower()
    if doc_type == "discussion":
        return "posts"

    return doc_type


def get_date_ranges_by_time_scope(time_scope):
    end_date = datetime.now()
    if time_scope == "all_time" or time_scope == "all":
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


def _should_cache(doc_type, flt, time_scope):
    if doc_type != BOUNTY.lower() and (flt == MOST_RSC or flt == EXPIRING_SOON):
        return False
    if time_scope != "today" and (
        flt == HOT or flt == MOST_RSC or flt == EXPIRING_SOON
    ):
        return False
    if time_scope != "all" and flt == NEW:
        return False
    return True


def reset_unified_document_cache(
    document_type=[
        ALL.lower(),
        POSTS.lower(),
        PREREGISTRATION.lower(),
        PAPER.lower(),
        QUESTION.lower(),
        BOUNTY.lower(),
    ],
    filters=[DISCUSSED, HOT, NEW, UPVOTED, EXPIRING_SOON, MOST_RSC],
    date_ranges=CACHE_DATE_RANGES,
    hub_id=0,  # Main feed
):
    for doc_type in document_type:
        for f in filters:
            for time_scope in date_ranges:
                if not _should_cache(doc_type, f, time_scope):
                    continue

                preload_trending_documents.apply_async(
                    (
                        doc_type,
                        hub_id,
                        f,
                        time_scope,
                    ),
                    priority=1,
                    countdown=3,
                )


def update_unified_document_to_paper(paper):
    from researchhub_document.models import ResearchhubUnifiedDocument

    unified_doc = ResearchhubUnifiedDocument.objects.filter(paper__id=paper.id)
    if unified_doc.exists():
        try:
            rh_unified_doc = unified_doc.first()
            curr_score = paper.score
            rh_unified_doc.score = curr_score
            hubs = paper.hubs.all()
            rh_unified_doc.hubs.add(*hubs)
            paper.calculate_hot_score()
            rh_unified_doc.save()
        except Exception as e:
            print(e)
            log_error(e)
