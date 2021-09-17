# TODO: Fix the celery task on cloud deploys
from time import time
from django.db import models
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.admin.options import get_content_type_for_model
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from bullet_point.models import BulletPoint, Vote as BulletPointVote
from bullet_point.serializers import BulletPointVoteSerializer
from discussion.models import Comment, Reply, Thread
from discussion.models import Vote as ReactionVote
from notification.models import Notification
from paper.models import Paper, Vote as PaperVote
from purchase.models import Wallet
from reputation import distributions
from reputation.distributor import Distributor
from researchhub.settings import TESTING
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from hypothesis.models import Hypothesis
from summary.models import Summary, Vote as SummaryVote
from summary.serializers import SummaryVoteSerializer
from utils.siftscience import events_api, decisions_api
from user.models import Action, Author, User, Organization
from user.tasks import (
    link_author_to_papers, link_paper_to_authors, handle_spam_user_task
)


@receiver(post_save, sender=Organization, dispatch_uid='add_organization_slug')
def add_organization_slug(
    sender,
    instance,
    created,
    update_fields,
    **kwargs
):
    if created:
        suffix = get_random_string(length=32)
        slug = slugify(instance.name)
        if not slug:
            slug += suffix
        instance.slug = slug
        instance.save()


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

        if len(thread.plain_text) <= 25 or duplicate_thread:
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
@receiver(post_save, sender=ReactionVote, dispatch_uid='discussion_vote_action')
@receiver(post_save, sender=BulletPointVote, dispatch_uid='summary_vote_action')
@receiver(post_save, sender=SummaryVote, dispatch_uid='bulletpoint_vote_action')
@receiver(post_save, sender=ResearchhubPost, dispatch_uid='researchhubpost_action')
@receiver(post_save, sender=Hypothesis, dispatch_uid='create_hypothesis_action')
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        elif sender == Paper:
            user = instance.uploaded_by
        else:
            if sender == Thread:
                thread = instance
                if thread.is_removed:
                    content_id = f'{type(thread).__name__}_{thread.id}'
                    decisions_api.apply_bad_content_decision(thread.created_by, content_id)
                    events_api.track_flag_content(
                        thread.created_by,
                        content_id,
                        1,
                    )
            user = instance.created_by

        """
        If we're creating an action for the first time,
        check if we've been referred
        """
        referral_content_types = [
            get_content_type_for_model(Thread),
            get_content_type_for_model(Reply),
            get_content_type_for_model(Comment),
            get_content_type_for_model(Paper),
            get_content_type_for_model(ResearchhubPost),
            get_content_type_for_model(Hypothesis)
        ]
        if (
            user is not None
            and user.invited_by
            and not Action.objects.filter(
                user=user, content_type__in=referral_content_types
            ).exists()
            and sender in [
                Thread,
                Reply,
                Comment,
                Paper,
                ResearchhubPost,
                Hypothesis
            ]
        ):
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

        vote_types = [
            PaperVote, ReactionVote, BulletPointVote, SummaryVote
        ]
        display = False if (
            sender in vote_types
            or sender != ReactionVote and (
                hasattr(instance, 'is_removed') and
                instance.is_removed
            )
        ) else True

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
        if hubs:
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
    if sender == ReactionVote or sender == PaperVote:
        return

    if created:
        for recipient in action.item.users_to_notify:
            recipient_exists = True
            if sender in (Summary, BulletPointVote, SummaryVote):
                return

            if sender == Paper:
                creator = instance.uploaded_by
                if instance.uploaded_by == creator:
                    return
                unified_document = instance.unified_document
            elif sender == ResearchhubPost:
                creator = instance.created_by
                unified_document = instance.unified_document
            elif sender == Hypothesis:
                creator = instance.created_by
                unified_document = instance.unified_document
            else:
                creator = instance.created_by
                unified_document = instance.unified_document

            if unified_document is None:
                return

            if type(recipient) is Author and recipient.user:
                recipient = recipient.user
            elif type(recipient) is Author and not recipient.user:
                recipient_exists = False

            if recipient != creator and recipient_exists:
                notification = Notification.objects.create(
                    unified_document=unified_document,
                    recipient=recipient,
                    action_user=creator,
                    action=action,
                )
                if not TESTING:
                    notification.send_notification()


def get_related_hubs(instance):
    try:
        paper = instance.paper
        if (paper is not None):
            return paper.hubs.all()
        elif (type(instance.item) is ResearchhubPost):
            return instance.item.unified_document.hubs.all()
    except AttributeError:
        return []


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
