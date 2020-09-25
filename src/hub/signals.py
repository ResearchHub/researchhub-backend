from django.db.models.signals import post_save
from django.dispatch import receiver

from paper.models import Paper


@receiver(post_save, sender=Paper, dispatch_uid='update_paper_count')
def update_paper_count(
    sender,
    instance: Paper,
    created: bool,
    update_fields,
    **kwargs
):
    """Update the paper count for relevant hubs"""

    for hub in instance.hubs.all():
        true_paper_count = hub.papers.count()
        if true_paper_count > hub.paper_count:
            hub.paper_count += 1
        elif true_paper_count < hub.paper_count:
            hub.paper_count -= 1
        hub.save()


@receiver(post_save, sender=Paper, dispatch_uid='update_discussion_count')
def update_discussion_count(
    sender,
    instance: Paper,
    created: bool,
    update_fields,
    **kwargs
):
    """Update the discussion count for relevant hubs"""

    for hub in instance.hubs.all():
        hub.discussion_count = sum(
            paper.discussion_count
            for paper
            in hub.papers.all()
        )
        hub.save()
