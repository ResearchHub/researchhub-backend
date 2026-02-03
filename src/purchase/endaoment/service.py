import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from authlib.integrations.base_client.errors import OAuthError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.utils import timezone

from purchase.endaoment.client import EndaomentClient
from purchase.related_models.endaoment_account_model import EndaomentAccount

logger = logging.getLogger(__name__)

User = get_user_model()


@dataclass
class CallbackResult:
    """
    Result of processing an OAuth callback.
    """

    success: bool
    return_url: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ConnectionStatus:
    """
    Endaoment connection status for a user.
    """

    connected: bool
    endaoment_user_id: Optional[str] = None


class EndaomentService:
    """
    Service for managing Endaoment connections and operations.
    """

    def __init__(self, client: Optional[EndaomentClient] = None):
        self.client = client or EndaomentClient()

    def get_authorization_url(
        self, user_id: int, return_url: Optional[str] = None
    ) -> str:
        """
        Generate the Endaoment OAuth authorization URL.

        Args:
            user_id: ID of the authenticated user.
            return_url: URL to redirect after OAuth completion.

        Returns:
            Authorization URL for redirecting the user.
        """
        return self.client.build_authorization_url(user_id, return_url)

    def process_callback(
        self,
        code: Optional[str],
        state: str,
        error: Optional[str] = None,
    ) -> CallbackResult:
        """
        Process the OAuth callback from Endaoment.

        Args:
            code: Authorization code from Endaoment.
            state: Signed state token.
            error: Error code if user cancelled or an error occurred.
        """
        if error or not code:
            return CallbackResult(success=False, error="cancelled")

        try:
            state_data = self.client.validate_state(state)
        except signing.BadSignature:
            logger.warning("Invalid or expired Endaoment state token")
            return CallbackResult(success=False, error="invalid_state")

        user_id = state_data.get("user_id")
        code_verifier = state_data.get("code_verifier")

        if not user_id or not code_verifier:
            return CallbackResult(success=False, error="invalid_state")

        try:
            token_response = self.client.fetch_token(code, code_verifier)
            user = User.objects.get(id=user_id)
            self._save_account(user, token_response)
            logger.info("Endaoment connected for user %s", user_id)
            return CallbackResult(success=True, return_url=state_data.get("return_url"))

        except User.DoesNotExist:
            logger.error("User %s not found during Endaoment callback", user_id)
            return CallbackResult(success=False, error="error")
        except Exception:
            logger.exception("Failed to process Endaoment callback")
            return CallbackResult(success=False, error="error")

    def get_connection_status(self, user) -> ConnectionStatus:
        """
        Check if a user has an Endaoment connection.
        """
        account = EndaomentAccount.objects.filter(user=user).first()
        if account:
            return ConnectionStatus(True, account.endaoment_user_id)
        return ConnectionStatus(False)

    def get_valid_access_token(self, user) -> Optional[str]:
        """
        Get a valid access token for the user, refreshing if necessary.

        Returns None if user has no Endaoment account.
        """
        account = EndaomentAccount.objects.filter(user=user).first()
        if not account:
            return None

        if account.is_token_expired() and account.refresh_token:
            self._refresh_account_token(account)

        return account.access_token

    def get_user_funds(self, user) -> list:
        """
        Get the user's DAFs from Endaoment.

        Returns:
            List of fund objects from Endaoment API.

        Raises:
            EndaomentAccount.DoesNotExist: If user has no Endaoment connection.
        """
        access_token = self.get_valid_access_token(user)
        if not access_token:
            raise EndaomentAccount.DoesNotExist(
                "User has no Endaoment connection"
            )
        return self.client.get_user_funds(access_token)

    def _refresh_account_token(self, account: EndaomentAccount) -> None:
        """
        Refresh the access token for an account.
        """
        try:
            token_response = self.client.refresh_access_token(account.refresh_token)
        except OAuthError as e:
            if e.error == "invalid_grant":
                # If the token is invalid, revoked or expired, delete the account.
                # See: https://datatracker.ietf.org/doc/html/rfc6749#section-5.2
                logger.warning(
                    f"Failed to refresh token for user {account.user.id}: {e}"
                )
                account.delete()
            else:
                logger.error(
                    f"Unexpected OAuth error refreshing token for user {account.user.id}: {e}"
                )
            raise

        account.access_token = token_response.access_token
        if token_response.refresh_token:
            account.refresh_token = token_response.refresh_token
        account.token_expires_at = timezone.now() + timedelta(
            seconds=token_response.expires_in
        )
        account.save(
            update_fields=["access_token", "refresh_token", "token_expires_at"]
        )

    def _save_account(self, user, token_response) -> EndaomentAccount:
        """
        Save (or update) the Endaoment account for a user.

        Args:
            user: The user to save the account for.
            token_response: Token response from Endaoment.
        """

        account, _ = EndaomentAccount.objects.update_or_create(
            user=user,
            defaults={
                "access_token": token_response.access_token,
                "refresh_token": token_response.refresh_token,
                "token_expires_at": timezone.now()
                + timedelta(seconds=token_response.expires_in),
            },
        )
        return account

    @staticmethod
    def build_redirect_url(
        error: Optional[str] = None, return_url: Optional[str] = None
    ) -> str:
        """
        Build redirect URL with success or error query params.

        Args:
            error: Error code to include in URL.
            return_url: Custom return URL.

        Returns:
            Redirect URL with appropriate query parameters.
        """
        base = (
            return_url
            if EndaomentClient.is_valid_redirect_url(return_url)
            else settings.BASE_FRONTEND_URL
        )
        sep = "&" if "?" in base else "?"

        if error:
            return f"{base}{sep}endaoment_error={error}"
        return f"{base}{sep}endaoment_connected=true"
