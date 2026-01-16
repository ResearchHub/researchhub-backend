from allauth.account.signals import user_logged_in, user_signed_up
from django.dispatch import receiver

from oauth.services.user_signup_service import UserSignupService


@receiver(user_signed_up)
def handle_user_signup(request, user, **kwargs):
    """
    Add user email to Mailchimp and track signup in Amplitude.
    """
    service = UserSignupService()
    service.add_to_mailchimp(user)
    service.track_signup(request, user, **kwargs)


@receiver(user_signed_up)
@receiver(user_logged_in)
def handle_google_profile_image(sender, request, user, **kwargs):
    """
    After a user signs up or logs in with social account, set their profile image.
    """
    service = UserSignupService()
    service.set_google_profile_image(user)
