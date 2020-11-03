# TODO: Fix the celery task on cloud deploys
from time import time

from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider

from reputation import distributions
from bullet_point.models import BulletPoint
from discussion.models import Comment, Reply, Thread
from notification.models import Notification
from paper.models import Paper, Vote as PaperVote
from discussion.models import Vote as DisVote
from researchhub.settings import TESTING
from summary.models import Summary
from user.models import Action, Author
from user.tasks import link_author_to_papers, link_paper_to_authors
from reputation.distributor import Distributor


@receiver(post_save, sender=Author, dispatch_uid='link_author_to_papers')
def queue_link_author_to_papers(sender, instance, created, **kwargs):
    """Runs a queued task to link the new ORCID author to existing papers."""
    if created:
        try:
            orcid_account = SocialAccount.objects.get(
                user=instance.user,
                provider=OrcidProvider.id
            )
            if not TESTING:
                link_author_to_papers.apply_async(
                    (instance.id, orcid_account.id)
                )
            else:
                link_author_to_papers(instance.id, orcid_account.id)
        except SocialAccount.DoesNotExist:
            pass


@receiver(post_save, sender=Paper, dispatch_uid='link_paper_to_authors')
def queue_link_paper_to_authors(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    """Runs a queued task linking ORCID authors to papers with updated dois."""
    if created or doi_updated(update_fields):
        if instance.doi is not None:
            try:
                if not TESTING:
                    link_paper_to_authors.apply_async(
                        (instance.id,)
                    )
                else:
                    link_paper_to_authors(instance.id)
            except SocialAccount.DoesNotExist:
                pass


def doi_updated(update_fields):
    if update_fields is not None:
        return 'doi' in update_fields
    return False


@receiver(
    pre_save,
    sender=BulletPoint,
    dispatch_uid='create_bullet_point_handle_spam'
)
@receiver(pre_save, sender=Summary, dispatch_uid='create_summary_handle_spam')
@receiver(pre_save, sender=Comment, dispatch_uid='create_comment_handle_spam')
@receiver(pre_save, sender=Reply, dispatch_uid='create_reply_handle_spam')
@receiver(pre_save, sender=Thread, dispatch_uid='create_thread_handle_spam')
@receiver(pre_save, sender=Paper, dispatch_uid='paper_handle_spam')
@receiver(pre_save, sender=PaperVote, dispatch_uid='paper_vote_action')
def handle_spam(sender, instance, **kwargs):
    # If user is a probable spammer, mark all of their content as is_removed
    
    if sender == Paper:
        user = instance.uploaded_by
    elif sender in (Comment, Reply, Thread, BulletPoint, PaperVote):
        user = instance.created_by
    elif sender in (Summary,):
        user = instance.proposed_by

    if user and user.probable_spammer:
        instance.is_removed = True


@receiver(
    post_save,
    sender=BulletPoint,
    dispatch_uid='create_bullet_point_action'
)
@receiver(post_save, sender=Summary, dispatch_uid='create_summary_action')
@receiver(post_save, sender=Comment, dispatch_uid='create_comment_action')
@receiver(post_save, sender=Reply, dispatch_uid='create_reply_action')
@receiver(post_save, sender=Thread, dispatch_uid='create_thread_action')
@receiver(post_save, sender=Paper, dispatch_uid='paper_upload_action')
@receiver(post_save, sender=PaperVote, dispatch_uid='paper_vote_action')
@receiver(post_save, sender=DisVote, dispatch_uid='discussion_vote_action')
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        elif sender == Paper:
            user = instance.uploaded_by
        else:
            user = instance.created_by

        # If we're creating an action for the first time, check if we've been referred
        if user.invited_by and not Action.objects.filter(user=user).exists():
            timestamp = time()
            referred = Distributor(
                distributions.Referral,
                user,
                user.invited_by,
                timestamp,
                None,
            )
            referred.distribute()

            referrer = Distributor(
                distributions.Referral,
                user.invited_by,
                user.invited_by,
                timestamp,
                None,
            )
            referrer.distribute()

        display = True
        if sender == PaperVote:
            display = False
        elif sender == DisVote:
            display = False
        else:
            display = True

        action = Action.objects.create(
            item=instance,
            user=user,
            display=display
        )

        if sender == Paper:
            hubs = instance.hubs.all()
        else:
            hubs = get_related_hubs(instance)
        action.hubs.add(*hubs)
        create_notification(sender, instance, created, action, **kwargs)

        return action


@receiver(post_delete, sender=Paper, dispatch_uid='paper_delete_action')
def create_delete_action(sender, instance, using, **kwargs):
    display = False
    action = Action.objects.create(
        item=instance,
        display=display
    )
    return action


def create_notification(sender, instance, created, action, **kwargs):
    if sender == DisVote or sender == PaperVote:
        return

    if created:
        for recipient in action.item.users_to_notify:
            recipient_exists = True
            if sender == Summary:
                creator = instance.proposed_by
                paper = instance.paper
            elif sender == Paper:
                creator = instance.uploaded_by
                paper = instance
            else:
                creator = instance.created_by
                paper = instance.paper

            if type(recipient) is Author and recipient.user:
                recipient = recipient.user
            elif type(recipient) is Author and not recipient.user:
                recipient_exists = False

            if recipient != creator and recipient_exists:
                notification = Notification.objects.create(
                    paper=paper,
                    recipient=recipient,
                    action_user=creator,
                    action=action,
                )
                if not TESTING:
                    notification.send_notification()


def get_related_hubs(instance):
    paper = instance.paper
    return paper.hubs.all()
