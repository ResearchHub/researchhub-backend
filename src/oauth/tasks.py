from celery import shared_task
from django.contrib.auth import get_user_model
from django.db import DatabaseError

from oauth.services import sync_orcid_for_user


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_orcid_for_user_task(self, user_id: int) -> None:
    """Enqueueable task to sync ORCID data for the given user id."""
    import logging

    logger = logging.getLogger(__name__)

    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for ORCID sync")
        return

    logger.info(f"Starting ORCID sync for user {user_id}")
    try:
        sync_orcid_for_user(user)
        logger.info(f"Successfully completed ORCID sync for user {user_id}")
    except DatabaseError as exc:
        # Database errors should be retried as they might be transient
        logger.error(f"ORCID sync database error for user {user_id}: {exc}")
        raise self.retry(exc=exc)
    except Exception as exc:  # pragma: no cover - retry path
        logger.error(f"ORCID sync failed for user {user_id}: {exc}")
        raise self.retry(exc=exc)
