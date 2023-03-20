import requests
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from bullet_point.models import BulletPoint
from bullet_point.models import Vote as BulletPointVote
from discussion.models import Vote as GrmVote
from hypothesis.models import Hypothesis
from mailing_list.tasks import build_notification_context
from paper.models import Paper, PaperSubmission
from purchase.models import Wallet
from reputation.models import Bounty
from researchhub.settings import NO_ELASTIC, TESTING
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from summary.models import Summary
from summary.models import Vote as SummaryVote
from user.constants.organization_constants import PERSONAL
from user.models import Action, Author, Organization, User
from user.tasks import (
    handle_spam_user_task,
    link_author_to_papers,
    link_paper_to_authors,
)
from utils.message import send_email_message
from utils.sentry import log_error
from utils.siftscience import decisions_api, events_api


@receiver(pre_save, sender=Organization, dispatch_uid="add_organization_slug")
def add_organization_slug(sender, instance, update_fields, **kwargs):
    if not instance.slug:
        suffix = get_random_string(length=32)
        slug = slugify(instance.name)
        if not slug:
            slug += suffix
        if sender.objects.filter(slug__icontains=slug).exists():
            slug += f"-{suffix}"
        instance.slug = slug


@receiver(post_save, sender=User, dispatch_uid="handle_spam_user")
def handle_spam_user(sender, instance, created, update_fields, **kwargs):
    # TODO: move this to overriding the save method of the model instead of post_save here
    if instance.probable_spammer and not NO_ELASTIC:
        handle_spam_user_task.apply_async((instance.id,), priority=3)


@receiver(post_save, sender=Author, dispatch_uid="link_author_to_papers")
def queue_link_author_to_papers(sender, instance, created, **kwargs):
    """Runs a queued task to link the new ORCID author to existing papers."""
    if created:
        try:
            orcid_account = SocialAccount.objects.get(
                user=instance.user, provider=OrcidProvider.id
            )
            if not TESTING:
                link_author_to_papers.apply_async((instance.id, orcid_account.id))
            else:
                link_author_to_papers(instance.id, orcid_account.id)
        except SocialAccount.DoesNotExist:
            pass


# TODO: See if this signal is still required. Was causing a backlog of tasks on Celery
# @receiver(post_save, sender=Paper, dispatch_uid="link_paper_to_authors")
# def queue_link_paper_to_authors(sender, instance, created, update_fields, **kwargs):
#     """Runs a queued task linking ORCID authors to papers with updated dois."""
#     if created or doi_updated(update_fields):
#         if instance.doi is not None:
#             try:
#                 link_paper_to_authors.apply_async((instance.id,))
#             except SocialAccount.DoesNotExist:
#                 pass


def doi_updated(update_fields):
    if update_fields is not None:
        return "doi" in update_fields
    return False


@receiver(post_save, sender=BulletPoint, dispatch_uid="create_bullet_point_action")
@receiver(post_save, sender=Summary, dispatch_uid="create_summary_action")
@receiver(post_save, sender=RhCommentModel, dispatch_uid="creation_rh_comment")
@receiver(post_save, sender=Paper, dispatch_uid="paper_upload_action")
@receiver(post_save, sender=GrmVote, dispatch_uid="discussion_vote_action")
@receiver(post_save, sender=BulletPointVote, dispatch_uid="summary_vote_action")
@receiver(post_save, sender=SummaryVote, dispatch_uid="bulletpoint_vote_action")
@receiver(post_save, sender=ResearchhubPost, dispatch_uid="researchhubpost_action")
@receiver(post_save, sender=Hypothesis, dispatch_uid="create_hypothesis_action")
@receiver(post_save, sender=PaperSubmission, dispatch_uid="create_submission_action")
@receiver(post_save, sender=Bounty, dispatch_uid="create_bounty_action")
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Summary:
            user = instance.proposed_by
        elif sender == Paper or sender == PaperSubmission:
            user = instance.uploaded_by
        else:
            if sender == RhCommentModel:
                thread = instance
                if thread.is_removed:
                    content_id = f"{type(thread).__name__}_{thread.id}"
                    decisions_api.apply_bad_content_decision(
                        thread.created_by, content_id
                    )
                    events_api.track_flag_content(
                        thread.created_by,
                        content_id,
                        1,
                    )
            user = instance.created_by

        vote_types = [GrmVote, BulletPointVote, SummaryVote]
        display = (
            False
            if (
                sender in vote_types
                or sender == PaperSubmission
                or sender != GrmVote
                and (hasattr(instance, "is_removed") and instance.is_removed)
            )
            else True
        )

        action = Action.objects.create(item=instance, user=user, display=display)

        hubs = get_related_hubs(instance)
        if hubs:
            action.hubs.add(*hubs)

        send_discussion_email_notification(instance, sender, action)
        return action


def send_discussion_email_notification(instance, sender, action):
    if sender != RhCommentModel:
        return

    for recipient in instance.users_to_notify:
        creator = instance.created_by
        if recipient != creator:
            email_preference = getattr(recipient, "emailrecipient", None)
            subscription = None
            try:
                # Checks if the recipient has an email recipient obj
                if not email_preference:
                    return

                subscription = email_preference.comment_subscription
                subject = "ResearchHub | Someone created a discussion on your post"
                if (
                    email_preference.receives_notifications
                    and subscription
                    and not subscription.none
                ):
                    context = build_notification_context([action])
                    send_email_message(
                        recipient.email,
                        "notification_email.txt",
                        subject,
                        context,
                        html_template="notification_email.html",
                    )
            except Exception as e:
                log_error(e)


@receiver(post_delete, sender=Paper, dispatch_uid="paper_delete_action")
def create_delete_action(sender, instance, using, **kwargs):
    display = False
    action = Action.objects.create(item=instance, display=display)
    return action


def get_related_hubs(instance):
    try:
        if isinstance(
            instance,
            (Paper, ResearchhubPost, Hypothesis, RhCommentModel, Bounty),
        ):
            return instance.unified_document.hubs.all()
        elif isinstance(instance, PaperSubmission):
            paper = instance.paper
            if paper:
                return instance.paper.hubs.all()
        elif hasattr(instance, "hubs"):
            return instance.hubs.all()
        return []
    except AttributeError:
        return []


@receiver(models.signals.post_save, sender=User)
def attach_author_and_email_preference(sender, instance, created, *args, **kwargs):
    if created:
        author = Author.objects.create(
            user=instance,
            first_name=instance.first_name,
            last_name=instance.last_name,
        )
        Wallet.objects.create(author=author)


@receiver(post_save, sender=User, dispatch_uid="user_create_org")
def create_user_organization(sender, instance, created, **kwargs):
    if created:
        suffix = get_random_string(length=32)
        name = f"{instance.first_name} {instance.last_name}'s Notebook"
        slug = slugify(name)
        if not slug:
            slug += suffix
        if Organization.objects.filter(slug__icontains=slug).exists():
            slug += f"-{suffix}"

        content_type = ContentType.objects.get_for_model(Organization)
        org = Organization.objects.create(
            name=name, org_type=PERSONAL, slug=slug, user=instance
        )
        Permission.objects.create(
            access_type=ADMIN,
            content_type=content_type,
            object_id=org.id,
            organization=org,
            user=instance,
        )

        profile_image = instance.author_profile.profile_image
        try:
            if profile_image:
                request = requests.get(profile_image.url, allow_redirects=False)
                if request.status_code == 200:
                    profile_image_content = request.content
                    profile_image_file = ContentFile(profile_image_content)
                    org.cover_image.save(
                        f"org_image_{instance.id}_{slug}.png",
                        profile_image_file,
                        save=True,
                    )
        except Exception as e:
            log_error(e)
