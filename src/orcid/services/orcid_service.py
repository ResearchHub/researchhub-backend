from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import requests
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone


class OrcidService:
    ORCID_BASE_URL = "https://orcid.org"
    STATE_MAX_AGE = 600

    def __init__(self, base_url: str = ORCID_BASE_URL):
        self.base_url = base_url

    def build_auth_url(self, user_id: int, return_url: Optional[str] = None) -> str:
        app = self._get_orcid_app()
        state_data = {"user_id": user_id}
        if self._is_valid_redirect_url(return_url):
            state_data["return_url"] = return_url
        params = {
            "client_id": app.client_id,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": settings.ORCID_REDIRECT_URL,
            "state": self._encode_signed_value(state_data),
        }
        return f"{self.base_url}/oauth/authorize?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        app = self._get_orcid_app()
        response = requests.post(
            f"{self.base_url}/oauth/token",
            headers={"Accept": "application/json"},
            data={
                "client_id": app.client_id,
                "client_secret": app.secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.ORCID_REDIRECT_URL,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def connect_orcid_account(self, user: Any, token_data: Dict[str, Any]) -> None:
        if "orcid" not in token_data:
            raise ValueError("Invalid ORCID response")

        orcid_id = token_data["orcid"]
        already_linked = (
            SocialAccount.objects
            .filter(provider=OrcidProvider.id, uid=orcid_id)
            .exclude(user=user)
            .exists()
        )
        if already_linked:
            raise ValueError("ORCID already linked to another account")

        with transaction.atomic():
            extra_data = {
                "name": token_data.get("name", ""),
                "scope": token_data.get("scope", ""),
            }

            account, _ = SocialAccount.objects.update_or_create(
                user=user,
                provider=OrcidProvider.id,
                defaults={"uid": orcid_id, "extra_data": extra_data},
            )

            app = self._get_orcid_app()
            expires_at = None
            if expires_in := token_data.get("expires_in"):
                expires_at = timezone.now() + timedelta(seconds=expires_in)

            SocialToken.objects.update_or_create(
                account=account,
                app=app,
                defaults={
                    "token": token_data.get("access_token", ""),
                    "token_secret": token_data.get("refresh_token", ""),
                    "expires_at": expires_at,
                },
            )

            if author := getattr(user, "author_profile", None):
                author.orcid_id = f"{self.base_url}/{orcid_id}"
                author.save(update_fields=["orcid_id"])

    def decode_state(self, state: str) -> Optional[Dict[str, Any]]:
        return self._decode_signed_value(state, max_age=self.STATE_MAX_AGE)

    def get_redirect_url(self, error: Optional[str] = None, return_url: Optional[str] = None) -> str:
        base = return_url if self._is_valid_redirect_url(return_url) else settings.BASE_FRONTEND_URL
        separator = "&" if "?" in base else "?"
        if error:
            return f"{base}{separator}orcid_error={error}"
        return f"{base}{separator}orcid_connected=true"

    def _get_orcid_app(self) -> SocialApp:
        return SocialApp.objects.get(provider=OrcidProvider.id)

    def _is_valid_redirect_url(self, url: Optional[str]) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in settings.CORS_ORIGIN_WHITELIST

    def _encode_signed_value(self, value: Dict[str, Any]) -> str:
        return signing.dumps(value)

    def _decode_signed_value(self, signed_value: str, max_age: Optional[int] = None) -> Optional[Dict[str, Any]]:
        try:
            return signing.loads(signed_value, max_age=max_age)
        except signing.BadSignature:
            return None
