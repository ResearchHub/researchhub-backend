from researchhub_document.tasks import (
    preload_trending_documents
)
from researchhub_document.related_models.constants.document_type import (
    PAPER,
    POST,
    ALL,
)


def reset_unified_document_cache(
    hub_ids,
    document_type=[ALL.lower(), POST.lower(), PAPER.lower()],
    ordering='-hot_score',
    time_difference=0
):

    for doc_type in document_type:
        for hub_id in hub_ids:
            preload_trending_documents.apply_async(
                (
                    doc_type,
                    hub_id,
                    ordering,
                    time_difference,
                ),
                priority=1
            )
