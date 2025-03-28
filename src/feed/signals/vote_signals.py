import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.reaction_models import Vote
from feed.serializers import serialize_feed_metrics
from feed.tasks import update_feed_metrics

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Vote, dispatch_uid="feed_vote")
def handle_feed_vote(instance, sender, **kwargs):
    if not isinstance(instance, Vote):
        return

    if not instance.item:
        return

    if (
        instance.content_type.model == "paper"
        or instance.content_type.model == "researchhubpost"
        or instance.content_type.model == "rhcommentmodel"
    ):
        metrics = serialize_feed_metrics(instance.item, instance.content_type)

        update_feed_metrics.apply_async(
            args=(
                instance.item.id,
                instance.content_type.id,
                metrics,
            ),
            priority=1,
        )
