import logging
from datetime import timedelta
from typing import Optional, Tuple

from allauth.socialaccount.models import SocialAccount, SocialApp, SocialToken
from allauth.socialaccount.providers.orcid.provider import OrcidProvider
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone

from orcid.clients import OrcidClient
from orcid.config import ORCID_BASE_URL, STATE_MAX_AGE
from orcid.utils import get_orcid_app, is_valid_redirect_url

User = get_user_model()
logger = logging.getLogger(__name__)


class OrcidCallbackService:
    """Handles ORCID OAuth callback: validates state, exchanges tokens, stores connection."""

    def __init__(self, client: Optional[OrcidClient] = None):
        self.client = client or OrcidClient()
        self._orcid_app = None

    def process_callback(self, code: str, state: str) -> str:
        """Validates state, fetches token, saves ORCID connection."""
        return_url = None
        try:
            user, return_url = self._validate_state(state)
            token_data = self._fetch_token(code)
            self._save_orcid_connection(user, token_data)
            logger.info("ORCID connected for user %s: %s", user.id, token_data.get("orcid"))
            return self.get_redirect_url(return_url=return_url)
        except ValueError:
            logger.warning("ORCID already linked to another account")
            return self.get_redirect_url(error="already_linked", return_url=return_url)
        except Exception:
            logger.exception("ORCID callback failed")
            return self.get_redirect_url(error="error", return_url=return_url)

    def get_redirect_url(self, error: Optional[str] = None, return_url: Optional[str] = None) -> str:
        """Build redirect URL with success or error query params."""
        base = return_url if is_valid_redirect_url(return_url) else settings.BASE_FRONTEND_URL
        sep = "&" if "?" in base else "?"
        return f"{base}{sep}orcid_error={error}" if error else f"{base}{sep}orcid_connected=true"

    def _validate_state(self, state: str) -> Tuple[User, Optional[str]]:
        """Decode and validate the signed state token, returning user and return_url."""
        try:
            state_data = signing.loads(state, max_age=STATE_MAX_AGE)
        except signing.BadSignature:
            raise signing.BadSignature("Invalid state")
        user = User.objects.get(id=state_data.get("user_id"))
        return user, state_data.get("return_url")

    def _fetch_token(self, code: str) -> dict:
        """Exchange authorization code for ORCID access token."""
        app = self._get_orcid_app()
        token_data = self.client.exchange_code_for_token(
            code=code, client_id=app.client_id, client_secret=app.secret,
            redirect_uri=settings.ORCID_REDIRECT_URL,
        )
        if "orcid" not in token_data:
            raise RuntimeError("Missing ORCID in response")
        return token_data

    def _save_orcid_connection(self, user: User, token_data: dict) -> None:
        """Save ORCID connection: social account, token, and author profile."""
        orcid_id = token_data["orcid"]

        with transaction.atomic():
            self._verify_orcid_not_linked(orcid_id, user)
            account = self._create_social_account(user, orcid_id, token_data)
            self._store_oauth_token(account, token_data)
            self._update_author_orcid(user, orcid_id)

    def _verify_orcid_not_linked(self, orcid_id: str, user: User) -> None:
        """Raise ValueError if ORCID is already linked to another user."""
        if SocialAccount.objects.filter(provider=OrcidProvider.id, uid=orcid_id).exclude(user=user).exists():
            raise ValueError("ORCID already linked to another account")

    def _create_social_account(self, user: User, orcid_id: str, token_data: dict) -> SocialAccount:
        """Create or update the user's ORCID social account."""
        extra_data = {
            "name": token_data.get("name", ""),
            "scope": token_data.get("scope", ""),
        }
        account, _ = SocialAccount.objects.update_or_create(
            user=user, provider=OrcidProvider.id,
            defaults={"uid": orcid_id, "extra_data": extra_data},
        )
        return account

    def _store_oauth_token(self, account: SocialAccount, token_data: dict) -> None:
        """Store the OAuth access and refresh tokens."""
        expires_at = None
        if expires_in := token_data.get("expires_in"):
            expires_at = timezone.now() + timedelta(seconds=expires_in)
        SocialToken.objects.update_or_create(
            account=account, app=self._get_orcid_app(),
            defaults={
                "token": token_data.get("access_token", ""),
                "token_secret": token_data.get("refresh_token", ""),
                "expires_at": expires_at,
            },
        )

    def _update_author_orcid(self, user: User, orcid_id: str) -> None:
        """Update the user's author profile with their ORCID URL."""
        if author := getattr(user, "author_profile", None):
            author.orcid_id = f"{ORCID_BASE_URL}/{orcid_id}"
            author.save(update_fields=["orcid_id"])

    def _get_orcid_app(self) -> SocialApp:
        """Get cached ORCID social app configuration."""
        if self._orcid_app is None:
            self._orcid_app = get_orcid_app()
        return self._orcid_app

