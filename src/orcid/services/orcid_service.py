import logging
from datetime import timedelta
from typing import List, Optional, Tuple
from urllib.parse import urlencode, urlparse

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from orcid.clients.orcid_client import OrcidClient

User = get_user_model()
logger = logging.getLogger(__name__)


class OrcidService:
    """
    Handles ORCID OAuth flow: builds auth URLs, processes callbacks,
    and stores connection data.
    """

    ORCID_BASE_URL = "https://orcid.org"
    STATE_MAX_AGE = 600
    EDU_DOMAINS = (".edu", ".ac.uk", ".edu.au", ".ac.jp", ".edu.cn", ".gov")

    def __init__(self, client: OrcidClient = None):
        self.client = client or OrcidClient()

    def build_auth_url(self, user_id: int, return_url: Optional[str] = None) -> str:
        app = self._get_orcid_app()
        state_data = {"user_id": user_id}
        if self._is_valid_redirect_url(return_url):
            state_data["return_url"] = return_url
        params = {
            "client_id": app.client_id,
            "response_type": "code",
            "scope": "/authenticate",
            "redirect_uri": settings.ORCID_REDIRECT_URL,
            "state": self._encode_signed_value(state_data),
        }
        return f"{self.ORCID_BASE_URL}/oauth/authorize?{urlencode(params)}"

    def process_callback(self, code: str, state: str) -> str:
        """Validates state, fetches token, checks for verified .edu emails,
        saves ORCID connection, updates author profile, and returns redirect URL."""
        return_url = None
        try:
            user, return_url = self._validate_state(state)
            token_data = self._fetch_token(code)
            self._save_orcid_connection(user, token_data)
            logger.info(f"ORCID connected for user {user.id}: {token_data.get('orcid')}")
            return self.get_redirect_url(return_url=return_url)
        except ValueError as e:
            logger.warning(f"ORCID already linked: {e}")
            return self.get_redirect_url(error="already_linked", return_url=return_url)
        except Exception as e:
            logger.exception(f"ORCID callback failed: {e}")
            return self.get_redirect_url(error="error", return_url=return_url)

    def get_redirect_url(self, error: Optional[str] = None, return_url: Optional[str] = None) -> str:
        base = return_url if self._is_valid_redirect_url(return_url) else settings.BASE_FRONTEND_URL
        separator = "&" if "?" in base else "?"
        if error:
            return f"{base}{separator}orcid_error={error}"
        return f"{base}{separator}orcid_connected=true"

    def _validate_state(self, state: str) -> Tuple[User, Optional[str]]:
        state_data = self._decode_state(state)
        if not state_data:
            raise signing.BadSignature("Invalid state")
        user = User.objects.get(id=state_data.get("user_id"))
        return user, state_data.get("return_url")

    def _fetch_token(self, code: str) -> dict:
        app = self._get_orcid_app()
        token_data = self.client.exchange_code_for_token(
            code=code,
            client_id=app.client_id,
            client_secret=app.secret,
            redirect_uri=settings.ORCID_REDIRECT_URL,
        )
        if "orcid" not in token_data:
            raise RuntimeError("Missing ORCID in response")
        return token_data

    def _save_orcid_connection(self, user: User, token_data: dict) -> None:
        orcid_id = token_data["orcid"]
        access_token = token_data.get("access_token", "")
        verified_edu_emails = self._fetch_verified_edu_emails(orcid_id, access_token)

        with transaction.atomic():
            self._verify_orcid_not_linked(orcid_id, user)
            account = self._create_or_update_social_account(
                user, orcid_id, token_data, verified_edu_emails
            )
            self._store_oauth_token(account, token_data)
            self._update_author_orcid(user, orcid_id)

    def _verify_orcid_not_linked(self, orcid_id: str, user: User) -> None:
        already_linked = (
            SocialAccount.objects
            .filter(provider=OrcidProvider.id, uid=orcid_id)
            .exclude(user=user)
            .exists()
        )
        if already_linked:
            raise ValueError("ORCID already linked to another account")

    def _create_or_update_social_account(
        self, user: User, orcid_id: str, token_data: dict, verified_edu_emails: List[str]
    ) -> SocialAccount:
        extra_data = {
            "name": token_data.get("name", ""),
            "scope": token_data.get("scope", ""),
            "verified_edu_emails": verified_edu_emails,
        }
        account, _ = SocialAccount.objects.update_or_create(
            user=user,
            provider=OrcidProvider.id,
            defaults={"uid": orcid_id, "extra_data": extra_data},
        )
        if verified_edu_emails:
            logger.info(f"User {user.id} has verified .edu emails: {verified_edu_emails}")
        return account

    def _fetch_verified_edu_emails(self, orcid_id: str, access_token: str) -> List[str]:
        """Fetch verified .edu emails from ORCID (if user has them set to public)."""
        emails = self.client.get_emails(orcid_id, access_token)
        logger.info(f"Fetched emails from ORCID: {emails}")
        return [
            e["email"] for e in emails
            if e.get("verified") and self._is_edu_email(e.get("email", ""))
        ]

    def _is_edu_email(self, email: str) -> bool:
        """Check if email is from an academic domain."""
        email_lower = email.lower()
        return any(email_lower.endswith(domain) for domain in self.EDU_DOMAINS)

    def _store_oauth_token(self, account: SocialAccount, token_data: dict) -> None:
        app = self._get_orcid_app()
        expires_at = None
        if expires_in := token_data.get("expires_in"):
            expires_at = timezone.now() + timedelta(seconds=expires_in)

        SocialToken.objects.update_or_create(
            account=account,
            app=app,
            defaults={
                "token": token_data.get("access_token", ""),
                "token_secret": token_data.get("refresh_token", ""),
                "expires_at": expires_at,
            },
        )

    def _update_author_orcid(self, user: User, orcid_id: str) -> None:
        if author := getattr(user, "author_profile", None):
            author.orcid_id = f"{self.ORCID_BASE_URL}/{orcid_id}"
            author.save(update_fields=["orcid_id"])

    def _decode_state(self, state: str) -> Optional[dict]:
        try:
            return signing.loads(state, max_age=self.STATE_MAX_AGE)
        except signing.BadSignature:
            return None

    def _get_orcid_app(self) -> SocialApp:
        return SocialApp.objects.get(provider=OrcidProvider.id)

    def _is_valid_redirect_url(self, url: Optional[str]) -> bool:
        if not url:
            return False
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return origin in settings.CORS_ORIGIN_WHITELIST

    def _encode_signed_value(self, value: dict) -> str:
        return signing.dumps(value)
