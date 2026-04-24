from researchhub.celery import app
from search.utils import bulk_remove_from_search_index


@app.task(ignore_result=True)
def cleanup_removed_content_from_search_index():
    """Safety-net task that removes stale content from the OpenSearch index.

    Catches items that were bulk-updated with ``is_removed=True`` but never
    synced to the index (e.g. if a prior removal call failed).
    """
    from paper.models import Paper
    from researchhub_document.related_models.researchhub_post_model import (
        ResearchhubPost,
    )

    bulk_remove_from_search_index(Paper.objects.filter(is_removed=True))
    bulk_remove_from_search_index(
        ResearchhubPost.objects.filter(unified_document__is_removed=True)
    )
