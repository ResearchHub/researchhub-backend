import logging

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from mailchimp_marketing import Client

from analytics.amplitude import Amplitude
from user.models import User, UserVerification

logger = logging.getLogger(__name__)


class UserSignupService:
    """
    Service for handling user signup side effects:
     - Registration in Mailchimp.
     - Tracking in Amplitude.
    """

    def __init__(
        self,
        amplitude_client=None,
        mailchimp_client=None,
        mailchimp_enabled=None,
    ):
        self.amplitude_client = amplitude_client or Amplitude()
        self.mailchimp_client = mailchimp_client or Client()

        # By default, enable Mailchimp integration in production environment only
        self.mailchimp_enabled = (
            mailchimp_enabled if mailchimp_enabled is not None else settings.PRODUCTION
        )

    def add_to_mailchimp(self, user):
        """
        Adds user email to MailChimp mailing list.
        """
        if not self.mailchimp_enabled:
            logger.info(f"Skipping MailChimp registration for user {user.id}")
            return

        self.mailchimp_client.set_config(
            {
                "api_key": settings.MAILCHIMP_KEY,
                "server": settings.MAILCHIMP_SERVER,
            }
        )
        try:
            member_info = {"email_address": user.email, "status": "subscribed"}
            self.mailchimp_client.lists.add_list_member(
                settings.MAILCHIMP_LIST_ID, member_info
            )
        except Exception as e:
            logger.error(f"Failed to add user {user.id} to MailChimp: {e}")

    def track_signup(self, request, user, **kwargs):
        """
        Tracks user signup event in Amplitude.
        """

        class TempResponse:
            def __init__(self, user):
                self.data = {"id": user.id}

        class TempView:
            def __init__(self):
                self.__dict__ = {"basename": "user", "action": "signup"}

        try:
            request.user = user
            res = TempResponse(user)
            view = TempView()
            self.amplitude_client.build_hit(res, view, request, **kwargs)
        except Exception as e:
            logger.error(f"Failed to track signup for user {user.id} in Amplitude: {e}")

    def set_social_profile_image(self, user: User) -> None:
        """Set the user's profile image from a social account if not already set."""
        for provider in ("google", "x_oauth2"):
            try:
                social_account = SocialAccount.objects.get(provider=provider, user=user)
                break
            except SocialAccount.DoesNotExist:
                continue
            except SocialAccount.MultipleObjectsReturned:
                logger.error(f"User {user.id} has multiple {provider} social accounts")
                return
        else:
            return

        picture_field = "picture" if provider == "google" else "profile_image_url"
        picture_url = social_account.extra_data.get(picture_field)
        if not picture_url:
            return

        author_profile = getattr(user, "author_profile", None)
        if author_profile and not author_profile.profile_image:
            author_profile.profile_image = picture_url
            author_profile.save(update_fields=["profile_image"])

    def set_x_profile_link(self, user: User) -> None:
        """Set the author's X profile link from their X account if not already set."""
        author_profile = getattr(user, "author_profile", None)
        if not author_profile or author_profile.twitter:
            return

        social_account = self._get_x_account(user)
        if not social_account:
            return

        username = social_account.extra_data.get("username")
        if not username:
            return

        author_profile.twitter = f"https://x.com/{username}"
        author_profile.save(update_fields=["twitter"])

    def verify_x_identity(self, user: User) -> None:
        """Approve the user's verification when X reports their identity as verified."""
        if user.is_verified:
            return

        social_account = self._get_x_account(user)
        if not social_account:
            return

        if not social_account.extra_data.get("is_identity_verified"):
            return

        UserVerification.objects.update_or_create(
            user=user,
            defaults={
                "first_name": user.first_name,
                "last_name": user.last_name,
                "status": UserVerification.Status.APPROVED,
                "verified_by": UserVerification.Type.X,
                "external_id": social_account.uid,
            },
        )

    def _get_x_account(self, user: User) -> SocialAccount | None:
        """Return the user's X social account, or None if they don't have exactly one."""
        try:
            return SocialAccount.objects.get(provider="x_oauth2", user=user)
        except SocialAccount.DoesNotExist:
            return None
        except SocialAccount.MultipleObjectsReturned:
            logger.error(f"User {user.id} has multiple X social accounts")
            return None
