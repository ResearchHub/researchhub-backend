"""Gmail OAuth for Expert Finder outreach mailbox connections.

Uses the existing Google SocialApp client.
Outreach requires gmail.send / gmail.readonly consent.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode, urlparse

import requests
from allauth.socialaccount.models import SocialApp
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from research_ai.models.outreach_mailbox_connection import (
    OutreachMailboxConnection,
    is_allowed_outreach_mailbox_email,
    normalize_outreach_mailbox_email,
)

User = get_user_model()
logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

GMAIL_OUTREACH_SCOPES = (
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
)

STATE_MAX_AGE = 600
REQUEST_TIMEOUT = 30


class GmailOAuthConfigError(Exception):
    """Google OAuth client credentials are not configured."""


class GmailOAuthError(Exception):
    """OAuth exchange or userinfo failed."""


class GmailMailboxNotAllowedError(Exception):
    """Connected account email is not a personal Gmail address."""

    def __init__(self, email: str):
        self.email = email
        super().__init__(f"Mailbox not allowed for outreach: {email}")


def is_valid_frontend_return_url(url: str | None) -> bool:
    """Validate optional FE return URL against CORS whitelist."""
    if not url:
        return False
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" in settings.CORS_ALLOWED_ORIGINS


def get_google_oauth_credentials() -> tuple[str, str]:
    """
    Load Google OAuth client_id/secret from SocialApp, then settings fallback.

    Same client as website Google login; do not create a separate OAuth client
    unless Google verification forces it.
    """
    try:
        app = SocialApp.objects.get(provider="google")
    except SocialApp.DoesNotExist:
        app = None

    client_id = (app.client_id if app else "") or getattr(
        settings, "GOOGLE_CLIENT_ID", ""
    )
    client_secret = (app.secret if app else "") or getattr(
        settings, "GOOGLE_CLIENT_SECRET", ""
    )
    if not client_id or not client_secret:
        raise GmailOAuthConfigError("Google OAuth client is not configured")
    return client_id, client_secret


class GmailOAuthClient:
    """Thin HTTP client for Google OAuth token / userinfo / revoke APIs."""

    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests

    def exchange_code_for_token(
        self,
        *,
        code: str,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        response = self.session.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        response = self.session.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    def revoke_token(self, token: str) -> None:
        """Best-effort revoke; ignores HTTP errors from Google."""
        try:
            self.session.post(
                GOOGLE_REVOKE_URL,
                data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException:
            logger.warning("Failed to revoke Google OAuth token", exc_info=True)


class GmailOAuthService:
    """Build auth URLs, handle callback, and disconnect outreach Gmail."""

    def __init__(self, client: GmailOAuthClient | None = None):
        self.client = client or GmailOAuthClient()

    def get_connection_status(self, user) -> dict[str, Any]:
        """Return mailbox status payload for GET mailbox/."""
        try:
            connection = user.outreach_mailbox_connection
        except OutreachMailboxConnection.DoesNotExist:
            return {
                "connected": False,
                "email": None,
                "status": None,
                "last_error": None,
            }

        connected = connection.status in {
            OutreachMailboxConnection.Status.ACTIVE,
            OutreachMailboxConnection.Status.NEEDS_REAUTH,
        }
        return {
            "connected": connected,
            "email": connection.email if connected else None,
            "status": connection.status,
            "last_error": connection.last_error or None,
        }

    def build_auth_url(
        self, user_id: int, return_url: str | None = None
    ) -> dict[str, str]:
        """Return Google OAuth URL + signed state for Connect Gmail."""
        client_id, _ = get_google_oauth_credentials()
        state_data: dict[str, Any] = {"user_id": user_id}
        if is_valid_frontend_return_url(return_url):
            state_data["return_url"] = return_url
        state = signing.dumps(state_data)
        params = {
            "client_id": client_id,
            "redirect_uri": settings.GMAIL_OUTREACH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(GMAIL_OUTREACH_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return {
            "auth_url": f"{GOOGLE_AUTH_URL}?{urlencode(params)}",
            "state": state,
        }

    def process_callback(self, code: str, state: str) -> str:
        """Exchange code, enforce personal Gmail, upsert connection, return FE URL."""
        return_url = None
        try:
            user, return_url = self._validate_state(state)
            token_data = self._exchange_code(code)
            email = self._email_from_token_response(token_data)
            self._save_connection(user, email=email, token_data=token_data)
            logger.info(
                "Gmail outreach mailbox connected for user %s: %s", user.id, email
            )
            return self.get_redirect_url(return_url=return_url)
        except GmailMailboxNotAllowedError as exc:
            logger.warning("Rejected non-Gmail outreach mailbox: %s", exc.email)
            return self.get_redirect_url(error="error", return_url=return_url)
        except Exception:
            logger.exception("Gmail outreach OAuth callback failed")
            return self.get_redirect_url(error="error", return_url=return_url)

    def disconnect(self, user) -> dict[str, Any]:
        """Revoke Google token if possible and mark connection revoked."""
        try:
            connection = user.outreach_mailbox_connection
        except OutreachMailboxConnection.DoesNotExist:
            return {
                "connected": False,
                "email": None,
                "status": None,
                "last_error": None,
            }

        token = connection.refresh_token or connection.access_token
        if token:
            self.client.revoke_token(token)

        # Mark revoked after Google revoke; leave ciphertext in place (tokens are
        # useless once revoked, and EncryptedTextField + NOT NULL rejects clears).
        connection.status = OutreachMailboxConnection.Status.REVOKED
        connection.access_token_expires_at = None
        connection.last_error = ""
        connection.save(
            update_fields=[
                "status",
                "access_token_expires_at",
                "last_error",
                "updated_date",
            ]
        )
        return {
            "connected": False,
            "email": None,
            "status": connection.status,
            "last_error": None,
        }

    def get_redirect_url(
        self, error: str | None = None, return_url: str | None = None
    ) -> str:
        """Build FE redirect with ?gmail=connected or ?gmail=error."""
        base = (
            return_url
            if is_valid_frontend_return_url(return_url)
            else settings.GMAIL_OUTREACH_FRONTEND_RETURN_URL
        )
        if not base:
            base = settings.BASE_FRONTEND_URL
        sep = "&" if "?" in base else "?"
        value = error or "connected"
        return f"{base}{sep}gmail={value}"

    def _validate_state(self, state: str) -> tuple[Any, str | None]:
        try:
            state_data = signing.loads(state, max_age=STATE_MAX_AGE)
        except signing.BadSignature as exc:
            raise GmailOAuthError("Invalid state") from exc
        user = User.objects.get(id=state_data.get("user_id"))
        return user, state_data.get("return_url")

    def _exchange_code(self, code: str) -> dict[str, Any]:
        client_id, client_secret = get_google_oauth_credentials()
        try:
            token_data = self.client.exchange_code_for_token(
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=settings.GMAIL_OUTREACH_REDIRECT_URI,
            )
        except requests.RequestException as exc:
            raise GmailOAuthError("Token exchange failed") from exc
        if not token_data.get("access_token"):
            raise GmailOAuthError("Missing access_token in Google response")
        return token_data

    def _email_from_token_response(self, token_data: Mapping[str, Any]) -> str:
        access_token = token_data["access_token"]
        try:
            userinfo = self.client.fetch_userinfo(access_token)
        except requests.RequestException as exc:
            raise GmailOAuthError("Failed to fetch Google userinfo") from exc

        email = normalize_outreach_mailbox_email(userinfo.get("email") or "")
        if not email:
            raise GmailOAuthError("Google userinfo missing email")
        if not is_allowed_outreach_mailbox_email(email):
            raise GmailMailboxNotAllowedError(email)
        return email

    @transaction.atomic
    def _save_connection(
        self, user, *, email: str, token_data: Mapping[str, Any]
    ) -> OutreachMailboxConnection:
        access_token = token_data.get("access_token") or ""
        refresh_token = token_data.get("refresh_token") or ""
        expires_in = int(token_data.get("expires_in") or 0)
        scope_str = token_data.get("scope") or " ".join(GMAIL_OUTREACH_SCOPES)
        scopes = [s for s in scope_str.split() if s]

        try:
            connection = OutreachMailboxConnection.objects.select_for_update().get(
                user=user
            )
        except OutreachMailboxConnection.DoesNotExist:
            connection = OutreachMailboxConnection(user=user)

        # Google omits refresh_token on re-consent if one was already issued.
        if not refresh_token and connection.refresh_token:
            refresh_token = connection.refresh_token
        if not refresh_token:
            raise GmailOAuthError("Google did not return a refresh_token")
        if not access_token:
            raise GmailOAuthError("Google did not return an access_token")

        connection.email = email
        connection.provider = OutreachMailboxConnection.Provider.GMAIL
        connection.access_token = access_token
        connection.refresh_token = refresh_token
        connection.access_token_expires_at = (
            timezone.now() + timedelta(seconds=expires_in) if expires_in else None
        )
        connection.scopes = scopes
        connection.status = OutreachMailboxConnection.Status.ACTIVE
        connection.last_error = ""
        connection.connected_at = timezone.now()
        connection.save()
        return connection
