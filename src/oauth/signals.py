from allauth.account.signals import user_signed_up
from allauth.socialaccount.helpers import _social_login
from django.db.models.signals import pre_social_login
from django.dispatch import receiver

from oauth.services.user_signup_service import UserSignupService


@receiver(pre_social_login)
def link_to_existing_user(sender, request, sociallogin, **kwargs):
    user = request.user
    if user:
        # If the user exists, connect this new social login to that user
        sociallogin.connect(request, user)
        # Notify the system that we took care of this login attempt
        _social_login(request, sociallogin)
    # No user found, continue with regular login process


@receiver(user_signed_up)
def handle_user_signup(request, user, **kwargs):
    """
    Add user email to Mailchimp and track signup in Amplitude.
    """
    service = UserSignupService()
    service.add_to_mailchimp(user)
    service.track_signup(request, user, **kwargs)
