from allauth.socialaccount.helpers import _social_login
from django.db.models.signals import pre_social_login, receiver


@receiver(pre_social_login)
def link_to_existing_user(sender, request, sociallogin, **kwargs):
    user = request.user
    if user:
        # If the user exists, connect this new social login to that user
        sociallogin.connect(request, user)
        # Notify the system that we took care of this login attempt
        _social_login(request, sociallogin)
    # No user found, continue with regular login process
