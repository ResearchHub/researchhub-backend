import logging
from typing import Optional

import requests

from orcid.config import APPLICATION_JSON , ORCID_API_URL, ORCID_BASE_URL

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30


class OrcidClient:
    """Client for ORCID OAuth API."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests

    def exchange_code_for_token(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> dict:
        """Exchange OAuth authorization code for access token."""
        response = self.session.post(
            f"{ORCID_BASE_URL}/oauth/token",
            headers={"Accept": APPLICATION_JSON },
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def get_email_data(self, orcid_id: str, access_token: str) -> dict:
        """Fetch user's email data from ORCID. Returns empty dict on error."""
        try:
            response = self.session.get(
                f"{ORCID_API_URL}/v3.0/{orcid_id}/email",
                headers={"Authorization": f"Bearer {access_token}", "Accept": APPLICATION_JSON },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            logger.warning("Failed to fetch email data for ORCID %s", orcid_id, exc_info=True)
            return {} 
