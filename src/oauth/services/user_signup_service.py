from django.conf import settings
from mailchimp_marketing import Client

from analytics.amplitude import Amplitude
from utils import sentry


class UserSignupService:
    """
    Service for handling user signup side effects:
     - Registration in Mailchimp.
     - Tracking in Amplitude.
    """

    def __init__(self, mailchimp_client=None, amplitude_client=None):
        self.mailchimp_client = mailchimp_client or Client()
        self.amplitude_client = amplitude_client or Amplitude()

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
        except Exception as error:
            sentry.log_error(error, message=error.text)

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
            sentry.log_error(e)
