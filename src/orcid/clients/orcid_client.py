from typing import Optional

import requests

from orcid.config import ORCID_BASE_URL

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
            headers={"Accept": "application/json"},
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

