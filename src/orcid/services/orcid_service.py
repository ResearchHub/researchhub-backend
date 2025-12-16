from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse

import requests
from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from orcid.clients.orcid_client import OrcidClient

User = get_user_model()


class OrcidService:
    STATE_MAX_AGE = 600

    def __init__(self, base_url: str = OrcidClient.ORCID_BASE_URL):
        self.base_url = base_url
        self.client = OrcidClient(base_url=base_url)

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

    def process_callback(self, code: str, state: str) -> str:
        state_data = self.decode_state(state)
        if not state_data:
            return self.get_redirect_url(error="invalid_state")

        return_url = state_data.get("return_url")

        try:
            user = User.objects.get(id=state_data.get("user_id"))
            token_data = self.exchange_code_for_token(code)
            if "orcid" not in token_data:
                return self.get_redirect_url(error="service_error", return_url=return_url)
            self.connect_orcid_account(user, token_data)
            return self.get_redirect_url(return_url=return_url)
        except User.DoesNotExist:
            return self.get_redirect_url(error="invalid_state", return_url=return_url)
        except ValueError:
            return self.get_redirect_url(error="already_linked", return_url=return_url)
        except (requests.RequestException, SocialApp.DoesNotExist):
            return self.get_redirect_url(error="service_error", return_url=return_url)

    def exchange_code_for_token(self, code: str) -> Dict[str, Any]:
        app = self._get_orcid_app()
        return self.client.exchange_code_for_token(
            code=code,
            client_id=app.client_id,
            client_secret=app.secret,
            redirect_uri=settings.ORCID_REDIRECT_URL,
        )

    def connect_orcid_account(self, user: Any, token_data: Dict[str, Any]) -> None:
        orcid_id = token_data["orcid"]
        self._verify_orcid_not_linked(orcid_id, user)

        with transaction.atomic():
            account = self._create_or_update_social_account(user, orcid_id, token_data)
            self._store_oauth_token(account, token_data)
            self._update_author_orcid(user, orcid_id)

    def _verify_orcid_not_linked(self, orcid_id: str, user: Any) -> None:
        already_linked = (
            SocialAccount.objects
            .filter(provider=OrcidProvider.id, uid=orcid_id)
            .exclude(user=user)
            .exists()
        )
        if already_linked:
            raise ValueError("ORCID already linked to another account")

    def _create_or_update_social_account(self, user: Any, orcid_id: str, token_data: Dict[str, Any]) -> SocialAccount:
        extra_data = {
            "name": token_data.get("name", ""),
            "scope": token_data.get("scope", ""),
        }
        account, _ = SocialAccount.objects.update_or_create(
            user=user,
            provider=OrcidProvider.id,
            defaults={"uid": orcid_id, "extra_data": extra_data},
        )
        return account

    def _store_oauth_token(self, account: SocialAccount, token_data: Dict[str, Any]) -> None:
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

    def _update_author_orcid(self, user: Any, orcid_id: str) -> None:
        if author := getattr(user, "author_profile", None):
            author.orcid_id = f"{self.base_url}/{orcid_id}"
            author.save(update_fields=["orcid_id"])

    def decode_state(self, state: str) -> Optional[Dict[str, Any]]:
        try:
            return signing.loads(state, max_age=self.STATE_MAX_AGE)
        except signing.BadSignature:
            return None

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
