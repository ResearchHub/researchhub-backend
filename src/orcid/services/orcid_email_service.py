from typing import Optional

from orcid.clients import OrcidClient
from orcid.config import EDU_DOMAINS


class OrcidEmailService:
    """Fetches and validates verified edu emails from ORCID."""

    def __init__(self, client: Optional[OrcidClient] = None):
        self.client = client or OrcidClient()

    def fetch_verified_edu_emails(self, orcid_id: str, access_token: str) -> list[str]:
        """Fetch verified edu emails, falling back to verified email domains if none found."""
        data = self.client.get_email_data(orcid_id, access_token)

        verified_edu = self._extract_verified_edu_emails(data)
        if verified_edu:
            return verified_edu

        return self._extract_verified_edu_domains(data)

    def _extract_verified_edu_emails(self, data: dict) -> list[str]:
        """Extract verified edu emails from ORCID email data."""
        emails = data.get("email", [])
        return [
            e["email"] for e in emails
            if e.get("verified") and self._is_edu(e.get("email", ""))
        ]

    def _extract_verified_edu_domains(self, data: dict) -> list[str]:
        """Extract verified edu domains from ORCID email data."""
        domains = data.get("email-domains", {}).get("email-domain", [])
        return [
            d["value"] for d in domains
            if d.get("verified") and self._is_edu(d.get("value", ""))
        ]

    def _is_edu(self, value: str) -> bool:
        """Check if email or domain is from an academic institution."""
        return any(value.lower().endswith(d) for d in EDU_DOMAINS)

