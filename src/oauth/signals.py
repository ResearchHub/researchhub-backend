from typing import Any

from allauth.account.signals import user_logged_in, user_signed_up
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.http import HttpRequest

from oauth.services.authorization_server_service import OAuthAuthorizationServerService
from oauth.services.user_signup_service import UserSignupService
from user.models import User


@receiver(post_save, sender=User)
def revoke_oauth_tokens_of_inactive_user(
    sender: type, instance: User, **kwargs: Any
) -> None:
    """
    Revokes the OAuth tokens of a deactivated user. DOT doesn't check whether the
    user is active when refreshing, and revoked tokens stay revoked if the account
    is reactivated.
    """
    if instance.is_active:
        return

    OAuthAuthorizationServerService().revoke_user_tokens(instance)


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
def handle_social_profile_image(
    sender: type, request: HttpRequest, user: User, **kwargs: Any
) -> None:
    """
    After a user signs up or logs in with social account, set their profile image.
    """
    service = UserSignupService()
    service.set_social_profile_image(user)


@receiver(user_signed_up)
@receiver(user_logged_in)
def handle_x_profile_link(
    sender: type, request: HttpRequest, user: User, **kwargs: Any
) -> None:
    """
    After a user signs up or logs in with X, link their X profile to their author.
    """
    service = UserSignupService()
    service.set_x_profile_link(user)
