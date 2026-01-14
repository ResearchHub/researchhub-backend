from typing import Optional

from orcid.clients import OrcidClient
from orcid.config import EDU_DOMAINS


class OrcidEmailService:
    """Fetches and validates verified edu emails from ORCID."""

    def __init__(self, client: Optional[OrcidClient] = None):
        self.client = client or OrcidClient()

    def fetch_verified_edu_emails(self, orcid_id: str, access_token: str) -> list[str]:
        """Fetch verified edu emails from ORCID."""
        data = self.client.get_email_data(orcid_id, access_token)
        emails = data.get("email", [])
        return [
            e["email"] for e in emails
            if e.get("verified") and self._is_edu(e.get("email", ""))
        ]

    def _is_edu(self, email: str) -> bool:
        """Check if email is from an academic institution."""
        return any(email.lower().endswith(d) for d in EDU_DOMAINS)
