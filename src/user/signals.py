# TODO: Fix the celery task on cloud deploys
from time import time
from django.db import models
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.admin.options import get_content_type_for_model

from bullet_point.models import BulletPoint, Vote as BulletPointVote
from bullet_point.serializers import BulletPointVoteSerializer
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as DisVote
from notification.models import Notification
from paper.models import Paper, Vote as PaperVote
from purchase.models import Wallet
from reputation import distributions
from reputation.distributor import Distributor
from researchhub.settings import TESTING
from summary.models import Summary, Vote as SummaryVote
from summary.serializers import SummaryVoteSerializer
from utils.siftscience import events_api, decisions_api
from user.models import Action, Author, User
from user.tasks import (
    link_author_to_papers, link_paper_to_authors, handle_spam_user_task
)


@receiver(
    post_save,
    sender=User,
    dispatch_uid='handle_spam_user'
)
def handle_spam_user(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    # TODO: move this to overriding the save method of the model instead of post_save here
    if instance.probable_spammer:
        handle_spam_user_task.apply_async((instance.id,), priority=3)

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
                link_paper_to_authors.apply_async(
                    (instance.id,)
                )
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

    if sender in (Thread,):
        thread = instance

        duplicate_thread = False
        if thread.plain_text:
            duplicate_thread = Thread.objects.filter(plain_text=thread.plain_text.strip(), paper=thread.paper).count() > 1

        if duplicate_thread:
            thread.is_removed = True

        if duplicate_thread:
            thread.created_by.probable_spammer = True
            thread.created_by.save()


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
@receiver(post_save, sender=BulletPointVote, dispatch_uid='summary_vote_action')
@receiver(post_save, sender=SummaryVote, dispatch_uid='bulletpoint_vote_action')
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        elif sender == Paper:
            user = instance.uploaded_by
        else:
            if sender == Thread:
                thread = instance
                duplicate_thread = False

                if thread.plain_text:
                    duplicate_thread = Thread.objects.filter(plain_text=thread.plain_text.strip(), paper=thread.paper).count() > 1

                if thread.is_removed:
                    content_id = f'{type(thread).__name__}_{thread.id}'
                    decisions_api.apply_bad_content_decision(thread.created_by, content_id)
                    events_api.track_flag_content(
                        thread.created_by,
                        content_id,
                        1,
                    )
            user = instance.created_by

        # If we're creating an action for the first time, check if we've been referred
        referral_content_types = [
            get_content_type_for_model(Thread),
            get_content_type_for_model(Reply),
            get_content_type_for_model(Comment),
            get_content_type_for_model(Paper)
        ]
        if user and user.invited_by and not Action.objects.filter(user=user, content_type__in=referral_content_types).exists() and sender in [Thread, Reply, Comment, Paper]:
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
        votes = (PaperVote, DisVote, BulletPointVote, SummaryVote)
        if sender in votes:
            display = False
        else:
            display = True

        if sender != DisVote and instance.is_removed:
            display = False

        action = Action.objects.create(
            item=instance,
            user=user,
            display=display
        )

        hubs = []
        if sender == Paper:
            hubs = instance.hubs.all()
        elif sender != BulletPointVote and sender != SummaryVote:
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
        extra = {}
        for recipient in action.item.users_to_notify:
            recipient_exists = True
            if sender == Summary:
                creator = instance.proposed_by
                paper = instance.paper
            elif sender == Paper:
                creator = instance.uploaded_by
                paper = instance
            elif sender == BulletPointVote:
                paper = instance.bulletpoint.paper
                creator = instance.created_by
                context = {'include_bullet_data': True}
                extra = BulletPointVoteSerializer(
                    instance,
                    context=context
                ).data
            elif sender == SummaryVote:
                paper = instance.summary.paper
                creator = instance.created_by
                context = {'include_summary_data': True}
                extra = SummaryVoteSerializer(
                    instance,
                    context=context
                ).data
            else:
                creator = instance.created_by
                paper = instance.paper

            if paper.uploaded_by == creator:
                return

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
                    extra={**extra}
                )
                if not TESTING:
                    notification.send_notification()


def get_related_hubs(instance):
    paper = instance.paper
    return paper.hubs.all()


@receiver(models.signals.post_save, sender=User)
def attach_author_and_email_preference(
    sender,
    instance,
    created,
    *args,
    **kwargs
):
    if created:
        author = Author.objects.create(
            user=instance,
            first_name=instance.first_name,
            last_name=instance.last_name,
        )
        Wallet.objects.create(author=author)
