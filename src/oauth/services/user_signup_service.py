import logging

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from mailchimp_marketing import Client

from analytics.amplitude import Amplitude
from mailing_list.services import EmailService
from user.models import User

logger = logging.getLogger(__name__)

WELCOME_EMAIL_SUBJECT = "Welcome to ResearchHub"


class UserSignupService:
    """
    Service for handling user signup side effects:
     - Registration in Mailchimp.
     - Tracking in Amplitude.
     - Sending the welcome email.
    """

    def __init__(
        self,
        amplitude_client=None,
        mailchimp_client=None,
        mailchimp_enabled=None,
        email_service: EmailService | None = None,
    ):
        self.amplitude_client = amplitude_client or Amplitude()
        self.mailchimp_client = mailchimp_client or Client()
        self.email_service = email_service or EmailService()

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

    def set_google_profile_image(self, user):
        """
        Set user's profile image from their Google account if not already set.
        """
        try:
            google_account = SocialAccount.objects.get(provider="google", user=user)
        except SocialAccount.DoesNotExist:
            return
        except SocialAccount.MultipleObjectsReturned:
            logger.error(f"User {user.id} has multiple Google social accounts")
            return

        picture_url = google_account.extra_data.get("picture")
        if not picture_url:
            return

        author_profile = getattr(user, "author_profile", None)
        if author_profile and not author_profile.profile_image:
            author_profile.profile_image = picture_url
            author_profile.save(update_fields=["profile_image"])

    def send_welcome_email(self, user: User) -> None:
        """
        Send the welcome email inviting a new user to complete their profile.
        """
        self.email_service.send_email(
            user.email,
            WELCOME_EMAIL_SUBJECT,
            {"first_name": user.first_name, "profile_url": user.frontend_view_link()},
            template="welcome_email",
        )
