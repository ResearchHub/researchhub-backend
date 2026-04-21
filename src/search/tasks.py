import logging

from researchhub.celery import app
from search.utils import sync_search_index

logger = logging.getLogger(__name__)


@app.task(ignore_result=True)
def cleanup_removed_content_from_search_index():
    """Safety-net task that removes stale content from the OpenSearch index.

    Catches items that were bulk-updated with ``is_removed=True`` but never
    synced to the index (e.g. if a ``sync_search_index`` call failed).
    """
    from paper.models import Paper
    from researchhub_document.related_models.researchhub_post_model import (
        ResearchhubPost,
    )

    sync_search_index(Paper.objects.filter(is_removed=True))
    sync_search_index(
        ResearchhubPost.objects.filter(unified_document__is_removed=True)
    )
