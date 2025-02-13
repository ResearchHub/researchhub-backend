from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from paper.models import Paper

"""
Signal handlers for Paper model.

The signal handlers are responsbile for creating and deleting feed entries
when papers are added to or removed from hubs.
"""


@receiver(m2m_changed, sender=Paper.hubs.through, dispatch_uid="paper_hubs_changed")
def handle_paper_hubs_changed(sender, instance, action, pk_set, **kwargs):
    if action == "post_add":
        for hub_id in pk_set:
            if isinstance(instance, Paper):
                hub = instance.hubs.get(id=hub_id)
                paper = instance
            else:  # instance is Hub
                hub = instance
                paper = hub.papers.get(id=hub_id)

            # We order feed entries by publish date, so we don't need to
            # create feed entries for papers that don't have a publish date
            if paper.paper_publish_date is None:
                continue

            create_feed_entry.apply_async(
                args=(
                    paper.id,
                    ContentType.objects.get_for_model(paper).id,
                    "PUBLISH",
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
    elif action == "post_remove":
        for hub_id in pk_set:
            if isinstance(instance, Paper):
                hub = Hub.objects.get(id=hub_id)
                paper = instance
            else:  # instance is Hub
                hub = instance
                paper = Paper.objects.get(id=hub_id)

            delete_feed_entry.apply_async(
                args=(
                    paper.id,
                    ContentType.objects.get_for_model(paper).id,
                    hub.id,
                    ContentType.objects.get_for_model(hub).id,
                ),
                priority=1,
            )
