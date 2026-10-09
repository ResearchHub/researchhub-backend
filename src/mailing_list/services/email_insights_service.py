"""SES v2 ``GetEmailAddressInsights`` client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings

from utils.aws import create_client

# Confidence levels returned by SES. Higher rank = stronger signal.
CONFIDENCE_LOW = "LOW"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_HIGH = "HIGH"
_CONFIDENCE_RANK = {
    CONFIDENCE_LOW: 1,
    CONFIDENCE_MEDIUM: 2,
    CONFIDENCE_HIGH: 3,
}


@dataclass(frozen=True)
class EmailAddressInsights:
    """Parsed ``MailboxValidation`` confidence fields from SES."""

    is_valid: str | None = None
    mailbox_exists: str | None = None
    is_disposable: str | None = None
    is_role_address: str | None = None
    is_random_input: str | None = None
    has_valid_syntax: str | None = None
    has_valid_dns_records: str | None = None


def confidence_at_least(verdict: str | None, minimum: str) -> bool:
    """True when ``verdict`` ranks at or above ``minimum`` (LOW < MEDIUM < HIGH)."""
    rank = _CONFIDENCE_RANK.get(str(verdict or "").strip().upper())
    min_rank = _CONFIDENCE_RANK.get(minimum)
    if rank is None or min_rank is None:
        return False
    return rank >= min_rank


def confidence_verdict(block: dict | None) -> str | None:
    """Extract a normalized ``ConfidenceVerdict`` from an SES insights block."""
    if not isinstance(block, dict):
        return None
    value = block.get("ConfidenceVerdict")
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def parse_mailbox_validation(response: dict | None) -> EmailAddressInsights:
    """Map a ``GetEmailAddressInsights`` response to ``EmailAddressInsights``."""
    mailbox = (response or {}).get("MailboxValidation") or {}
    evaluations = mailbox.get("Evaluations") or {}
    return EmailAddressInsights(
        is_valid=confidence_verdict(mailbox.get("IsValid")),
        mailbox_exists=confidence_verdict(evaluations.get("MailboxExists")),
        is_disposable=confidence_verdict(evaluations.get("IsDisposable")),
        is_role_address=confidence_verdict(evaluations.get("IsRoleAddress")),
        is_random_input=confidence_verdict(evaluations.get("IsRandomInput")),
        has_valid_syntax=confidence_verdict(evaluations.get("HasValidSyntax")),
        has_valid_dns_records=confidence_verdict(evaluations.get("HasValidDnsRecords")),
    )


class EmailInsightsService:
    """Thin SES ``GetEmailAddressInsights`` wrapper.

    Inject ``client`` in tests (any object with ``get_email_address_insights``).
    When omitted, builds a real ``sesv2`` client via ``utils.aws.create_client``.
    """

    def __init__(self, *, client: Any | None = None):
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            region = getattr(settings, "AWS_SES_REGION_NAME", None) or getattr(
                settings, "AWS_REGION_NAME", None
            )
            self._client = create_client("sesv2", region)
        return self._client

    def get_raw_insights(self, email: str) -> dict:
        """Return the raw SES ``GetEmailAddressInsights`` response."""
        return self.client.get_email_address_insights(EmailAddress=email)

    def get_insights(self, email: str) -> EmailAddressInsights:
        """Fetch and parse insights for ``email``. Propagates SES errors."""
        return parse_mailbox_validation(self.get_raw_insights(email))
