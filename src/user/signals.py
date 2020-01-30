from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from mailing_list.models import NotificationFrequencies
from mailing_list.tasks import *
from paper.models import Vote as PaperVote
from researchhub.settings import TESTING
from summary.models import Summary
from user.models import Action

@receiver(post_save, sender=Summary, dispatch_uid='create_summary_action')
@receiver(post_save, sender=Comment, dispatch_uid='create_comment_action')
@receiver(post_save, sender=Reply, dispatch_uid='create_reply_action')
@receiver(post_save, sender=Thread, dispatch_uid='create_thread_action')
@receiver(
    post_save,
    sender=DiscussionVote,
    dispatch_uid='create_discussion_vote_action'
)
@receiver(post_save, sender=PaperVote, dispatch_uid='create_paper_vote_action')
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        else:
            user = instance.created_by

        action = Action.objects.create(
            item=instance,
            user=user
        )

        hubs = get_related_hubs(instance)
        action.hubs.add(*hubs)
        return action

def get_related_hubs(instance):
    paper = instance.paper
    return paper.hubs.all()

@receiver(post_save, sender=Action, dispatch_uid='send_action_notification')
def send_immediate_action_notification(sender, instance, created, **kwargs):
    if created:
        if instance:
            notify_immediate.apply_async((instance.id,), priority=5)
            #notify_immediate(instance.id)
