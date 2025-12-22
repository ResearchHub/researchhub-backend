from typing import Optional
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing

from orcid.config import ORCID_BASE_URL
from orcid.utils import get_orcid_app, is_valid_redirect_url


class OrcidConnectService:
    """Handles initiating ORCID OAuth flow by building authorization URLs."""

    def build_auth_url(self, user_id: int, return_url: Optional[str] = None) -> str:
        """Build ORCID OAuth authorization URL with signed state token."""
        app = get_orcid_app()
        state_data = {"user_id": user_id}
        if is_valid_redirect_url(return_url):
            state_data["return_url"] = return_url
        params = {
            "client_id": app.client_id,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": settings.ORCID_REDIRECT_URL,
            "state": signing.dumps(state_data),
        }
        return f"{ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"

