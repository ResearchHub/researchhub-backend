from typing import Optional
from urllib.parse import urlencode, urlparse

from allauth.socialaccount.models import SocialApp
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.core import signing

from orcid.config.constants import ORCID_BASE_URL


class OrcidConnectService:
    """Handles initiating ORCID OAuth flow by building authorization URLs."""

    def build_auth_url(self, user_id: int, return_url: Optional[str] = None) -> str:
        """Build ORCID OAuth authorization URL with signed state token."""
        app = self._get_orcid_app()
        state_data = {"user_id": user_id}
        if self._is_valid_redirect_url(return_url):
            state_data["return_url"] = return_url
        params = {
            "client_id": app.client_id,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": settings.ORCID_REDIRECT_URL,
            "state": signing.dumps(state_data),
        }
        return f"{ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"

    def _get_orcid_app(self) -> SocialApp:
        """Get the ORCID social app configuration."""
        return SocialApp.objects.get(provider=OrcidProvider.id)

    def _is_valid_redirect_url(self, url: Optional[str]) -> bool:
        """Validate redirect URL against CORS whitelist."""
        if not url:
            return False
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}" in settings.CORS_ORIGIN_WHITELIST
