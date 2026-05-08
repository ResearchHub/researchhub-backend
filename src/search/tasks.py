import logging

from django.core.management import call_command

from researchhub.celery import app

logger = logging.getLogger(__name__)


@app.task
def remove_deleted_docs_from_index():
    """Periodic task to purge soft-deleted documents from OpenSearch indices."""
    logger.info("Starting removal of deleted docs from OpenSearch")
    call_command("remove_deleted_docs_from_index")
    logger.info("Finished removal of deleted docs from OpenSearch")
