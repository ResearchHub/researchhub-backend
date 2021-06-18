from researchhub_document.tasks import (
    preload_trending_documents
)


def reset_unified_document_cache(
    document_type,
    hub_ids,
    ordering='-hot_score',
    time_difference=0
):

    for hub_id in hub_ids:
        preload_trending_documents.apply_async(
            (
                document_type,
                hub_id,
                ordering,
                time_difference,
            ),
            priority=1
        )
