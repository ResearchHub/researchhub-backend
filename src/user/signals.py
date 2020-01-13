from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from mailing_list.lib import NotificationFrequencies
from mailing_list.models import EmailRecipient
from mailing_list.tasks import send_action_notification_emails
from paper.models import Vote as PaperVote
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
        return Action.objects.create(
            item=instance,
            user=user
        )


@receiver(post_save, sender=Action, dispatch_uid='send_action_notification')
def send_immediate_action_notification(sender, instance, created, **kwargs):
    if created:
        if isinstance(instance.item, Comment):
            email_recipient_ids = EmailRecipient.objects.filter(
                thread_subscription__isnull=False,
                comment_subscription_isnull=False,
                notification_frequency=NotificationFrequencies.IMMEDIATE
            ).values_list('id', flat=True)
            send_action_notification_emails.delay(email_recipient_ids)
