from allauth.socialaccount.models import SocialAccount
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from requests import HTTPError
from rest_framework import exceptions, serializers, status

from oauth.adapters import XOAuth2Adapter
from oauth.services.user_signup_service import UserSignupService
from user.models import User


class XAccountConflict(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This X account is connected to another user."
    default_code = "x_account_conflict"


class XConnectService:
    """Connects X accounts to signed-in users."""

    def connect_account(
        self, request: HttpRequest, user: User, access_token: str
    ) -> None:
        """Connect the X account behind the token and sync the author's X profile."""
        adapter = XOAuth2Adapter(request)
        try:
            extra_data = adapter.get_user_info(
                adapter.parse_token({"access_token": access_token})
            )
        except HTTPError as exc:
            raise serializers.ValidationError("Failed to fetch the X profile.") from exc
        uid = extra_data["id"]
        x_accounts = SocialAccount.objects.filter(provider=adapter.provider_id)
        with transaction.atomic():
            User.objects.select_for_update().get(pk=user.pk)
            if x_accounts.filter(uid=uid).exclude(user=user).exists():
                raise XAccountConflict
            if x_accounts.filter(user=user).exclude(uid=uid).exists():
                raise XAccountConflict("Another X account is already connected to you.")
            try:
                SocialAccount.objects.update_or_create(
                    provider=adapter.provider_id,
                    uid=uid,
                    user=user,
                    defaults={"extra_data": extra_data},
                )
            except IntegrityError as exc:
                raise XAccountConflict from exc
        signup_service = UserSignupService()
        signup_service.set_social_profile_image(user)
        signup_service.set_x_profile_link(user)
