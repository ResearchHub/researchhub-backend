from typing import Any, Dict

import requests


class OrcidClient:
    ORCID_BASE_URL = "https://orcid.org"

    def __init__(self, session: requests.Session = None):
        self.session = session or requests

    def exchange_code_for_token(
        self, code: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> Dict[str, Any]:
        response = self.session.post(
            f"{self.ORCID_BASE_URL}/oauth/token",
            headers={"Accept": "application/json"},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
