import logging

from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from django.dispatch import receiver

from feed.serializers import serialize_feed_metrics
from feed.tasks import update_feed_metrics
from paper.models import Paper

"""
Signal handlers for Paper model.

The signal handlers are responsible for updating feed entry metrics
when paper metadata changes, particularly when external metrics (altmetric)
are added or updated.
"""

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Paper, dispatch_uid="paper_external_metadata_updated")
def handle_paper_external_metadata_updated(sender, instance, update_fields, **kwargs):
    """
    Update feed entry metrics when a paper's external_metadata is updated.

    This ensures that altmetric data and other external metrics are reflected
    in the feed entries for the paper.
    """
    if not isinstance(instance, Paper):
        return

    # Only update if external_metadata field was updated
    if update_fields and "external_metadata" not in update_fields:
        return

    # Check if the paper has external metadata with metrics
    if not instance.external_metadata or "metrics" not in instance.external_metadata:
        return

    try:
        content_type = ContentType.objects.get_for_model(Paper)
        metrics = serialize_feed_metrics(instance, content_type)

        update_feed_metrics.apply_async(
            args=(
                instance.id,
                content_type.id,
                metrics,
            ),
            priority=3,  # Lower priority than votes/comments
        )

        logger.info(
            f"Scheduled feed metrics update for paper {instance.id} "
            f"after external_metadata change"
        )
    except Exception as e:
        logger.error(
            f"Failed to update feed metrics for paper {instance.id} "
            f"after external_metadata change: {e}",
            exc_info=True,
        )
