from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper


@receiver(post_save, sender=Paper, dispatch_uid='update_paper_count_create')
def update_paper_count_create(
    sender,
    instance: Paper,
    created: bool,
    update_fields,
    **kwargs
):
    """Update the paper count for the hub when a new paper is saved to it"""

    for hub in instance.hubs.all():
        true_paper_count = hub.papers.count()
        if true_paper_count > hub.paper_count:
            hub.paper_count += 1
        elif true_paper_count < hub.paper_count:
            hub.paper_count -= 1
        hub.save()
