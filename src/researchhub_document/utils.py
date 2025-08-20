from datetime import datetime, timedelta

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
            rh_unified_doc.save()
        except Exception as e:
            print(e)
            log_error(e)
