import logging

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from personalize.tasks import create_list_item_interaction_task
from user_lists.models import ListItem

logger = logging.getLogger(__name__)


@receiver(post_save, sender=ListItem, dispatch_uid="personalize_list_item_interaction")
def create_list_item_interaction(sender, instance, created, **kwargs):
    """
    Trigger creation of UserInteraction when a document is saved to a list (ListItem).
    """
    if not created:
        return

    def trigger_task():
        try:
            create_list_item_interaction_task.delay(instance.id)
        except Exception:
            logger.exception(
                "Exception triggering UserInteraction creation task for ListItem: %s",
                instance.id,
            )

    transaction.on_commit(trigger_task)
