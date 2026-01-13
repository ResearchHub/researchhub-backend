import logging

from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from mailchimp_marketing import Client

from analytics.amplitude import Amplitude

logger = logging.getLogger(__name__)


class UserSignupService:
    """
    Service for handling user signup side effects:
     - Registration in Mailchimp.
     - Tracking in Amplitude.
    """

    def __init__(self, amplitude_client=None, mailchimp_client=None):
        self.amplitude_client = amplitude_client or Amplitude()
        self.mailchimp_client = mailchimp_client or Client()

    def add_to_mailchimp(self, user):
        """
        Adds user email to MailChimp mailing list.
        """
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
        After a user signs up with social account, set their profile image.
        """
        queryset = SocialAccount.objects.filter(provider="google", user=user)

        if queryset.exists():
            if queryset.count() > 1:
                raise Exception(
                    f"Expected 1 item in the queryset. Found {queryset.count()}."
                )

            google_account = queryset.first()
            url = google_account.extra_data.get("picture", None)

            if user.author_profile and not user.author_profile.profile_image:
                user.author_profile.profile_image = url
                user.author_profile.save()
            return None

        else:
            return None
