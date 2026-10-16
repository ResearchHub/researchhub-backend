"""HTTP client for the Instantly API v2.

Auth is a Bearer token. The API key is injected via the constructor (defaults
to ``settings.INSTANTLY_API_KEY``) so tests can supply a fake key and session.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import requests
from django.conf import settings

BASE_URL = "https://api.instantly.ai/api/v2"
DEFAULT_TIMEOUT = (5, 30)

# Custom IMAP/SMTP (personal Gmail with app password).
PROVIDER_CODE_CUSTOM_IMAP_SMTP = 1

GMAIL_IMAP_HOST = "imap.gmail.com"
GMAIL_IMAP_PORT = 993
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587

DEFAULT_ACCOUNT_DAILY_LIMIT = 30

# Instantly account status codes.
ACCOUNT_STATUS_ACTIVE = 1
ACCOUNT_STATUS_PAUSED = frozenset({2, 3})
ACCOUNT_STATUS_ERROR = frozenset({-1, -2, -3})

# Weekday business-hours schedule used when creating/updating campaigns.
DEFAULT_CAMPAIGN_SCHEDULE: dict[str, Any] = {
    "schedules": [
        {
            "name": "Weekday Business Hours",
            "timing": {"from": "09:00", "to": "17:00"},
            "days": {
                "0": True,
                "1": True,
                "2": True,
                "3": True,
                "4": True,
                "5": False,
                "6": False,
            },
            "timezone": "America/Detroit",
        }
    ]
}


class InstantlyAPIError(Exception):
    """Raised when Instantly returns a non-success response or a transport error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: Any = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class InstantlyNotFoundError(InstantlyAPIError):
    """Raised when Instantly returns HTTP 404."""


class InstantlyClient:
    """Thin Instantly API v2 client. Dependencies are constructor-injected."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        session: requests.Session | None = None,
        base_url: str = BASE_URL,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ):
        self.api_key = (
            api_key
            if api_key is not None
            else getattr(settings, "INSTANTLY_API_KEY", "") or ""
        )
        self.session = session if session is not None else requests.Session()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def create_gmail_account(
        self,
        *,
        email: str,
        first_name: str,
        last_name: str,
        app_password: str,
        daily_limit: int = DEFAULT_ACCOUNT_DAILY_LIMIT,
        enable_slow_ramp: bool = True,
        reply_to: str | None = None,
    ) -> dict[str, Any]:
        """Create a custom IMAP/SMTP account for a personal Gmail address."""
        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "provider_code": PROVIDER_CODE_CUSTOM_IMAP_SMTP,
            "imap_username": email,
            "imap_password": app_password,
            "imap_host": GMAIL_IMAP_HOST,
            "imap_port": GMAIL_IMAP_PORT,
            "smtp_username": email,
            "smtp_password": app_password,
            "smtp_host": GMAIL_SMTP_HOST,
            "smtp_port": GMAIL_SMTP_PORT,
            "daily_limit": daily_limit,
            "enable_slow_ramp": enable_slow_ramp,
        }
        if reply_to:
            payload["reply_to"] = reply_to
        return self._request("POST", "/accounts", json=payload)

    def get_account(self, email: str) -> dict[str, Any]:
        """Fetch a single account by email address."""
        return self._request("GET", f"/accounts/{quote(email, safe='')}")

    def update_account(
        self,
        email: str,
        *,
        daily_limit: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """PATCH Instantly account fields (e.g. ``daily_limit``)."""
        payload: dict[str, Any] = dict(extra)
        if daily_limit is not None:
            payload["daily_limit"] = daily_limit
        if not payload:
            raise InstantlyAPIError("No account fields to update")
        return self._request(
            "PATCH", f"/accounts/{quote(email, safe='')}", json=payload
        )

    def delete_account(self, email: str) -> dict[str, Any] | None:
        """Delete an Instantly account. Returns None on empty 2xx bodies."""
        return self._request("DELETE", f"/accounts/{quote(email, safe='')}")

    def get_daily_account_analytics(
        self,
        emails: list[str],
        *,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Daily sent counts per account. ``emails`` is required by Instantly."""
        if not emails:
            return []
        params: list[tuple[str, str]] = [
            ("start_date", start_date),
            ("end_date", end_date),
        ]
        for email in emails:
            params.append(("emails[]", email))
        result = self._request("GET", "/accounts/analytics/daily", params=params)
        if result is None:
            return []
        if not isinstance(result, list):
            raise InstantlyAPIError(
                "Unexpected daily account analytics response shape",
                response_body=result,
            )
        return result

    def create_campaign(
        self,
        *,
        name: str,
        subject: str,
        body: str,
        email_list: list[str],
        daily_limit: int,
        campaign_schedule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a one-step email campaign for the given sending accounts."""
        payload = {
            "name": name,
            "campaign_schedule": campaign_schedule or DEFAULT_CAMPAIGN_SCHEDULE,
            "sequences": [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 0,
                            "variants": [{"subject": subject, "body": body}],
                        }
                    ]
                }
            ],
            "email_list": email_list,
            "daily_limit": daily_limit,
        }
        return self._request("POST", "/campaigns", json=payload)

    def update_campaign(
        self,
        campaign_id: str,
        *,
        subject: str | None = None,
        body: str | None = None,
        email_list: list[str] | None = None,
        daily_limit: int | None = None,
        campaign_schedule: dict[str, Any] | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """PATCH campaign fields used on republish / mailbox detach."""
        payload: dict[str, Any] = dict(extra)
        if subject is not None and body is not None:
            payload["sequences"] = [
                {
                    "steps": [
                        {
                            "type": "email",
                            "delay": 0,
                            "variants": [{"subject": subject, "body": body}],
                        }
                    ]
                }
            ]
        if email_list is not None:
            payload["email_list"] = email_list
        if daily_limit is not None:
            payload["daily_limit"] = daily_limit
        if campaign_schedule is not None:
            payload["campaign_schedule"] = campaign_schedule
        return self._request("PATCH", f"/campaigns/{campaign_id}", json=payload)

    def activate_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self._request("POST", f"/campaigns/{campaign_id}/activate")

    def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        return self._request("POST", f"/campaigns/{campaign_id}/pause")

    def add_leads(
        self,
        *,
        campaign_id: str,
        leads: list[dict[str, Any]],
        skip_if_in_workspace: bool = True,
    ) -> dict[str, Any]:
        """Bulk-add up to 1000 leads to a campaign (``POST /leads/add``)."""
        payload = {
            "campaign_id": campaign_id,
            "skip_if_in_workspace": skip_if_in_workspace,
            "leads": leads,
        }
        return self._request("POST", "/leads/add", json=payload)

    def delete_leads(
        self,
        *,
        campaign_id: str,
        lead_ids: list[str],
    ) -> dict[str, Any] | None:
        """
        Bulk-delete leads from a campaign (``DELETE /leads``).

        Only removes those leads from the given campaign.
        """
        if not lead_ids:
            return None
        payload = {
            "campaign_id": campaign_id,
            "ids": lead_ids,
        }
        return self._request("DELETE", "/leads", json=payload)

    def send_test_email(
        self,
        *,
        from_email: str,
        to_email: str,
        subject: str,
        html: str,
    ) -> dict[str, Any] | None:
        """
        Send a preview/test email via Instantly (``POST /emails/test``).
        """
        payload = {
            "eaccount": from_email,
            "to_address_email_list": to_email,
            "subject": subject,
            "body": {"html": html},
        }
        return self._request("POST", "/emails/test", json=payload)

    def init_google_oauth(self) -> dict[str, Any]:
        """
        Start Google Workspace OAuth (``POST /oauth/google/init``).
        """
        return self._request("POST", "/oauth/google/init", json={})

    def get_oauth_session_status(self, session_id: str) -> dict[str, Any]:
        """
        Poll an OAuth session (``GET /oauth/session/status/{session_id}``).
        """
        encoded = quote(session_id, safe="")
        return self._request("GET", f"/oauth/session/status/{encoded}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: list[tuple[str, str]] | dict[str, Any] | None = None,
    ) -> Any:
        if not self.api_key:
            raise InstantlyAPIError("INSTANTLY_API_KEY is not configured")

        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise InstantlyAPIError(f"Instantly request failed: {exc}") from exc

        if response.status_code == 404:
            raise InstantlyNotFoundError(
                f"Instantly resource not found: {method} {path}",
                status_code=404,
                response_body=_safe_json(response),
            )
        if not (200 <= response.status_code < 300):
            body = _safe_json(response)
            raise InstantlyAPIError(
                f"Instantly {method} {path} failed with {response.status_code}: "
                f"{_truncate_error_detail(body)}",
                status_code=response.status_code,
                response_body=body,
            )
        if not response.content:
            return None
        return _safe_json(response)


def _safe_json(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _truncate_error_detail(value: Any, *, max_len: int = 500) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
