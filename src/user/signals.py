import logging

import requests
from allauth.account.models import EmailAddress
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from discussion.models import Vote
from mailing_list.lib import base_email_context
from paper.models import Paper, PaperSubmission
from purchase.models import Wallet
from reputation.models import Bounty
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_comment.models import RhCommentModel
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.constants.organization_constants import PERSONAL
from user.models import Action, Author, Organization, User
from utils.message import send_email_message
from utils.sentry import log_error

logger = logging.getLogger(__name__)


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


def doi_updated(update_fields):
    if update_fields is not None:
        return "doi" in update_fields
    return False


@receiver(post_save, sender=RhCommentModel, dispatch_uid="creation_rh_comment")
@receiver(post_save, sender=Paper, dispatch_uid="paper_upload_action")
@receiver(post_save, sender=Vote, dispatch_uid="discussion_vote_action")
@receiver(post_save, sender=ResearchhubPost, dispatch_uid="researchhubpost_action")
@receiver(post_save, sender=PaperSubmission, dispatch_uid="create_submission_action")
@receiver(post_save, sender=Bounty, dispatch_uid="create_bounty_action")
def create_action(sender, instance, created, **kwargs):
    if created:
        if sender == Paper or sender == PaperSubmission:
            user = instance.uploaded_by
        else:
            user = instance.created_by

        vote_types = [Vote]
        display = (
            False
            if (
                sender in vote_types
                or sender == PaperSubmission
                or (
                    sender != Vote
                    and (hasattr(instance, "is_removed") and instance.is_removed)
                )
                or (sender == RhCommentModel and not instance.is_public)
                or (sender == Bounty and instance.parent)  # Only show parent bounties
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
                    context = {
                        **base_email_context,
                        "actions": [action.email_context()],
                    }
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
        if isinstance(instance, (Paper, ResearchhubPost, RhCommentModel, Bounty)):
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
        name = f"{instance.first_name} {instance.last_name}'s Org"
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


@receiver(post_save, sender=User, dispatch_uid="sync_email_address")
def sync_email_address_with_user(sender, instance, created, **kwargs):
    """
    Keep email addresses in `EmailAddress` model in sync with `User.email`.

    When the email address changes in the `User` model, we must ensure that
    the corresponding `EmailAddress` records are updated accordingly.

    This prevents login/password reset failures after email changes, since
    allauth requires a verified EmailAddress record matching User.email.
    """
    if not instance.email:
        return

    try:
        # Check if email address is already in sync
        current_primary = EmailAddress.objects.filter(
            user=instance, email=instance.email, verified=True, primary=True
        ).exists()

        if current_primary:
            return  # no changes needed

        with transaction.atomic():
            # First, mark all existing EmailAddress records as non-primary
            # This must happen before creating/updating to avoid unique constraint
            # violation on the (user_id, primary) constraint
            EmailAddress.objects.filter(user=instance).update(primary=False)

            # Get or create primary address with the user's current email
            email_address, email_created = EmailAddress.objects.get_or_create(
                user=instance,
                email=instance.email,
                defaults={"verified": True, "primary": True},
            )

            if not email_created:
                # If the email address already existed, ensure it's verified and primary
                email_address.verified = True
                email_address.primary = True
                email_address.save(update_fields=["verified", "primary"])

    except Exception as e:
        logger.error("Failed to sync email address for user %s: %s", instance.id, e)
