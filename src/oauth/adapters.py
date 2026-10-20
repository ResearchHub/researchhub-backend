from typing import Any

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialApp, SocialLogin, SocialToken
from allauth.socialaccount.providers.twitter_oauth2.views import (
    TwitterOAuth2Adapter as BaseTwitterOAuth2Adapter,
)
from django.http import HttpRequest
from rest_framework import serializers


class TwitterOAuth2Adapter(BaseTwitterOAuth2Adapter):
    def complete_login(
        self,
        request: HttpRequest,
        app: SocialApp,
        token: SocialToken,
        **kwargs: Any,
    ) -> SocialLogin:
        """Authenticate X users with their provider-confirmed email address."""
        login = super().complete_login(request, app, token, **kwargs)
        email = login.account.extra_data.get("confirmed_email")
        if not email:
            raise serializers.ValidationError(
                {
                    "confirmed_email": (
                        "X did not provide a confirmed email address. "
                        "Please confirm your email on X or use another sign-in method."
                    )
                }
            )
        email = serializers.EmailField(max_length=254).run_validation(email).lower()
        login.user.email = email
        login.email_addresses = [EmailAddress(email=email, primary=True, verified=True)]
        return login
