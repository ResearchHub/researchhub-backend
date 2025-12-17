from typing import Optional
from urllib.parse import urlencode, urlparse

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.core import signing


class OrcidService:
    ##  This service is used to build the auth URL for the ORCID OAuth flow.
    ##  It creates the correct parameters and encodes the basic state data
    ##  which will be used in the callback portion to validate and redirect the user back to the app.
    
    ORCID_BASE_URL = "https://orcid.org"

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
        return f"{self.ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"

    def _get_orcid_app(self) -> SocialApp:
        return SocialApp.objects.get(provider=OrcidProvider.id)

    def _is_valid_redirect_url(self, url: Optional[str]) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in settings.CORS_ORIGIN_WHITELIST

    def _encode_signed_value(self, value: dict) -> str:
        return signing.dumps(value)

