import logging

from django.contrib.auth import get_user_model

from oauth.services import sync_user_publications_from_orcid
from researchhub.celery import app

logger = logging.getLogger(__name__)
User = get_user_model()


@app.task
def sync_orcid_publications(user_id: int) -> None:
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error("User %s not found for ORCID sync", user_id)
        return

    logger.info("Starting ORCID sync for user %s", user_id)
    try:
        sync_user_publications_from_orcid(user)
        logger.info("ORCID sync completed for user %s", user_id)
    except Exception:
        logger.exception("ORCID sync failed for user %s", user_id)
        raise