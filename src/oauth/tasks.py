import logging
from django.contrib.auth import get_user_model

from oauth.services import sync_user_publications_from_orcid
from researchhub.celery import app

logger = logging.getLogger(__name__)


@app.task
def sync_orcid_for_user_task(user_id: int) -> None:
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for ORCID sync")
        return

    logger.info(f"Starting ORCID sync for user {user_id}")
    try:
        sync_user_publications_from_orcid(user)
        logger.info(f"Successfully completed ORCID sync for user {user_id}")
    except Exception as exc:
        logger.error(f"ORCID sync failed for user {user_id}: {exc}")
        raise
