"""SES v2 email validation.

Wraps ``GetEmailAddressInsights`` so the agent (and the server-side submit
gate) only keep addresses that look like real personal mailboxes. Role-like
locals (``info@``, ``contact@``, …) are rejected before any SES call.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from research_ai.services.agent import Tool, Toolset
from research_ai.services.expert_finder.display import ExpertDisplay
from utils.aws import create_client

logger = logging.getLogger(__name__)

# Confidence levels returned by SES. Higher rank = stronger signal.
CONFIDENCE_LOW = "LOW"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_HIGH = "HIGH"
_CONFIDENCE_RANK = {
    CONFIDENCE_LOW: 1,
    CONFIDENCE_MEDIUM: 2,
    CONFIDENCE_HIGH: 3,
}

# Gate: IsValid and MailboxExists must be at least this strong.
MIN_ACCEPT_CONFIDENCE = CONFIDENCE_MEDIUM

# Risk flags (disposable / SES role / random) reject at this strength or above.
MIN_REJECT_RISK_CONFIDENCE = CONFIDENCE_MEDIUM

# Locals that are almost never a personal professional address. Checked before
# SES so we avoid paying for known junk and keep the agent from anchoring on
# department inboxes.
ROLE_LOCAL_PARTS = frozenset(
    {
        "abuse",
        "admin",
        "admins",
        "admissions",
        "alumni",
        "billing",
        "comms",
        "communications",
        "contact",
        "contacts",
        "dept",
        "department",
        "donotreply",
        "do-not-reply",
        "enquiries",
        "enquiry",
        "general",
        "help",
        "helpdesk",
        "hello",
        "hr",
        "info",
        "information",
        "inquiries",
        "inquiry",
        "jobs",
        "mail",
        "marketing",
        "media",
        "noreply",
        "no-reply",
        "office",
        "postmaster",
        "press",
        "privacy",
        "reception",
        "recruiting",
        "recruitment",
        "sales",
        "security",
        "support",
        "team",
        "webmaster",
    }
)

EMAIL_VALIDATE = "email_validate"


@dataclass(frozen=True)
class EmailValidationResult:
    """Structured verdict for one address (tool output + server gate)."""

    email: str
    accepted: bool
    reason: str | None = None
    is_valid: str | None = None
    mailbox_exists: str | None = None
    is_disposable: str | None = None
    is_role_address: str | None = None
    is_random_input: str | None = None
    has_valid_syntax: str | None = None
    has_valid_dns_records: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _confidence_at_least(verdict: str | None, minimum: str) -> bool:
    rank = _CONFIDENCE_RANK.get(str(verdict or "").strip().upper())
    min_rank = _CONFIDENCE_RANK.get(minimum)
    if rank is None or min_rank is None:
        return False
    return rank >= min_rank


def is_role_local_part(email: str) -> bool:
    """True when the local part is a known shared/role mailbox label."""
    local = ExpertDisplay.normalize_email(email).split("@", 1)[0]
    # Strip plus-tags (info+dept@…) and dots that don't change the role label.
    local = local.split("+", 1)[0].replace(".", "")
    # Also match the undotted form against dotted role keys (no-reply).
    candidates = {local, local.replace("-", "")}
    for part in ROLE_LOCAL_PARTS:
        normalized = part.replace(".", "").replace("-", "")
        if part in candidates or normalized in candidates:
            return True
    return False


def _verdict(block: dict | None) -> str | None:
    if not isinstance(block, dict):
        return None
    value = block.get("ConfidenceVerdict")
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


class EmailValidationService:
    """SES ``GetEmailAddressInsights`` client with the expert-finder gate.

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

    def validate(self, email: str) -> EmailValidationResult:
        """Return an accept/reject verdict for ``email``.

        Never raises for expected validation failures; SES transport errors are
        logged and returned as ``accepted=False`` so submit stays fail-closed.
        """
        normalized = ExpertDisplay.normalize_email(email)
        if not normalized:
            return EmailValidationResult(
                email="", accepted=False, reason="email is required"
            )
        try:
            validate_email(normalized)
        except ValidationError:
            return EmailValidationResult(
                email=normalized,
                accepted=False,
                reason="invalid email syntax",
            )
        if is_role_local_part(normalized):
            return EmailValidationResult(
                email=normalized,
                accepted=False,
                reason="role-like local part rejected",
                is_role_address=CONFIDENCE_HIGH,
            )

        try:
            response = self.client.get_email_address_insights(EmailAddress=normalized)
        except Exception as exc:  # noqa: BLE001 - submit gate must fail closed
            # ClientError / BotoCoreError are the expected cases; anything else
            # still rejects so a bad mock or transient bug never accepts mail.
            if not isinstance(exc, (ClientError, BotoCoreError)):
                logger.exception("SES email insights failed for %r", normalized)
            else:
                logger.warning("SES email insights failed for %r: %s", normalized, exc)
            return EmailValidationResult(
                email=normalized,
                accepted=False,
                reason=f"ses insights unavailable: {exc}",
            )

        mailbox = (response or {}).get("MailboxValidation") or {}
        evaluations = mailbox.get("Evaluations") or {}
        is_valid = _verdict(mailbox.get("IsValid"))
        mailbox_exists = _verdict(evaluations.get("MailboxExists"))
        is_disposable = _verdict(evaluations.get("IsDisposable"))
        is_role_address = _verdict(evaluations.get("IsRoleAddress"))
        is_random_input = _verdict(evaluations.get("IsRandomInput"))
        has_valid_syntax = _verdict(evaluations.get("HasValidSyntax"))
        has_valid_dns = _verdict(evaluations.get("HasValidDnsRecords"))

        reason = self._reject_reason(
            is_valid=is_valid,
            mailbox_exists=mailbox_exists,
            is_disposable=is_disposable,
            is_role_address=is_role_address,
            is_random_input=is_random_input,
        )
        return EmailValidationResult(
            email=normalized,
            accepted=reason is None,
            reason=reason,
            is_valid=is_valid,
            mailbox_exists=mailbox_exists,
            is_disposable=is_disposable,
            is_role_address=is_role_address,
            is_random_input=is_random_input,
            has_valid_syntax=has_valid_syntax,
            has_valid_dns_records=has_valid_dns,
        )

    @staticmethod
    def _reject_reason(
        *,
        is_valid: str | None,
        mailbox_exists: str | None,
        is_disposable: str | None,
        is_role_address: str | None,
        is_random_input: str | None,
    ) -> str | None:
        if not _confidence_at_least(is_valid, MIN_ACCEPT_CONFIDENCE):
            return f"IsValid confidence {is_valid!r} below {MIN_ACCEPT_CONFIDENCE}"
        if not _confidence_at_least(mailbox_exists, MIN_ACCEPT_CONFIDENCE):
            return (
                f"MailboxExists confidence {mailbox_exists!r} below "
                f"{MIN_ACCEPT_CONFIDENCE}"
            )
        if _confidence_at_least(is_disposable, MIN_REJECT_RISK_CONFIDENCE):
            return f"disposable address (confidence {is_disposable!r})"
        if _confidence_at_least(is_role_address, MIN_REJECT_RISK_CONFIDENCE):
            return f"role address (confidence {is_role_address!r})"
        if _confidence_at_least(is_random_input, MIN_REJECT_RISK_CONFIDENCE):
            return f"random-looking address (confidence {is_random_input!r})"
        return None

    def is_accepted(self, email: str) -> bool:
        """True when ``email`` passes the expert-finder gate."""
        return self.validate(email).accepted

    def gate_submitted_experts(
        self, experts: list[dict] | None
    ) -> tuple[list[dict], list[str]]:
        """Server-side re-validation for ``submit_experts`` payloads.

        Never trusts model-side ``email_validate`` calls. Returns
        ``(kept_rows, drop_reasons)``. Rows without an accepted email are
        omitted; kept rows get a normalized ``email`` field.
        """
        kept: list[dict] = []
        drops: list[str] = []
        seen: set[str] = set()
        for index, row in enumerate(experts or []):
            if not isinstance(row, dict):
                drops.append(f"experts[{index}]: not an object")
                continue
            raw_email = row.get("email")
            result = self.validate(str(raw_email or ""))
            label = result.email or repr(raw_email)
            if not result.accepted:
                drops.append(
                    f"experts[{index}] ({label}): {result.reason or 'rejected'}"
                )
                continue
            if result.email in seen:
                drops.append(f"experts[{index}] ({result.email}): duplicate email")
                continue
            seen.add(result.email)
            kept.append({**row, "email": result.email})
        return kept, drops


class EmailValidateToolset:
    """Agent-facing ``email_validate`` tool over ``EmailValidationService``."""

    def __init__(self, *, service: EmailValidationService | None = None):
        self._service = service or EmailValidationService()

    @property
    def service(self) -> EmailValidationService:
        return self._service

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=EMAIL_VALIDATE,
                description=(
                    "Validate a professional email with AWS SES address "
                    "insights before submitting an expert. Rejects role-like "
                    "locals (info@, contact@, …) and addresses whose overall "
                    f"or mailbox confidence is below {MIN_ACCEPT_CONFIDENCE}. "
                    "Call this on every candidate email; the server re-checks "
                    "on submit_experts."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "email": {
                            "type": "string",
                            "description": "Candidate professional email address.",
                        }
                    },
                    "required": ["email"],
                },
                handler=self._email_validate,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _email_validate(self, args: dict) -> dict:
        email = str((args or {}).get("email") or "").strip()
        if not email:
            return {"error": "email is required"}
        return self._service.validate(email).as_dict()
