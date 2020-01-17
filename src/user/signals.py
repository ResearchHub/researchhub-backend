from django.db.models.signals import post_save
from django.dispatch import receiver

from discussion.models import Comment, Reply, Thread, Vote as DiscussionVote
from mailing_list.lib import NotificationFrequencies
from mailing_list.models import EmailRecipient
from mailing_list.tasks import send_action_notification_emails, send_email_simple
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

        if isinstance(instance, Summary):
            paper = instance.paper
            hubs = paper.hubs.all()
        if isinstance(instance, Comment):
            thread = data.parent
            paper = thread.paper
            hubs = paper.hubs.all()          
        if isinstance(instance, Reply):
            current = instance.item
            while not isinstance(current, Thread) and current.parent:
                current = current.parent

            if isinstance(current, Thread):
                paper = current.paper
                hubs = paper.hubs.all()
        if isinstance(instance, Thread):
            paper = instance.paper
            hubs = paper.hubs.all()
        if isinstance(instance, DiscussionVote):
            data = instance.item
            
            if isinstance(data, Comment):
                thread = data.parent
                paper = thread.paper
                hubs = paper.hubs.all()
            elif isinstance(data, Reply):
                current = data
                while not isinstance(current, Thread) and current.parent:
                    current = current.parent

                if isinstance(current, Thread):
                    paper = current.paper
                    hubs = paper.hubs.all()
            else:
                paper = data.paper
                hubs = paper.hubs.all()
            action.hubs.add(*hubs)
        if isinstance(instance, PaperVote):
            paper = instance.paper
            hubs = paper.hubs.all()
            action.hubs.add(*hubs)
        return action


@receiver(post_save, sender=Action, dispatch_uid='send_action_notification')
def send_immediate_action_notification(sender, instance, created, **kwargs):
    if created:
        if isinstance(instance.item, Comment):
            email_recipients = list(instance.item.parent.comments.all().values_list('created_by__email', flat=True).distinct('created_by'))
            email_recipient_ids = EmailRecipient.objects.filter(
                thread_subscription__isnull=False,
                comment_subscription__isnull=False,
                notification_frequency=NotificationFrequencies.IMMEDIATE
            ).values_list('id', flat=True)
            if TESTING:
                send_email_simple(email_recipients, instance.id)
                # send_action_notification_emails(email_recipient_ids)
            else:
                send_email_simple.delay(email_recipients, instance.id)
                # send_action_notification_emails.delay(email_recipient_ids)

        # if isinstance(instance.item, Reply):
