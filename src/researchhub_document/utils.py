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


def reset_unified_document_cache(
    hub_ids,
    document_type=[
        ALL.lower(),
        POSTS.lower(),
        PAPER.lower(),
        HYPOTHESIS.lower()
    ],
    ordering=['-hot_score', '-created_date', '-score'],
    time_difference=0,
    use_celery=True
):

    for doc_type in document_type:
        for hub_id in hub_ids:
            for order in ordering:
                if use_celery:
                    preload_trending_documents.apply_async(
                        (
                            doc_type,
                            hub_id,
                            order,
                            time_difference,
                        ),
                        priority=1,
                        countdown=1
                    )
                else:
                    preload_trending_documents(
                        doc_type,
                        hub_id,
                        order,
                        time_difference
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
