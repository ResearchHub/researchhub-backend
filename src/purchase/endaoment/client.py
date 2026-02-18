import logging
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from authlib.common.security import generate_token
from authlib.integrations.requests_client import OAuth2Session
from django.conf import settings
from django.core import signing

logger = logging.getLogger(__name__)


REQUEST_TIMEOUT = 30  # seconds


@dataclass
class TokenResponse:
    """
    Token response from Endaoment.
    """

    access_token: str
    refresh_token: str | None
    expires_in: int
    id_token: str | None = None
    token_type: str = "Bearer"


class EndaomentClient:
    """
    Client for Endaoment OAuth flow and API.

    See:
    - API docs: https://docs.endaoment.org/developers/getting-started/api-documentation
    """

    def __init__(self):
        self.api_url = settings.ENDAOMENT_API_URL
        self.auth_url = settings.ENDAOMENT_AUTH_URL
        self.client_id = settings.ENDAOMENT_CLIENT_ID
        self.client_secret = settings.ENDAOMENT_CLIENT_SECRET
        self.redirect_url = settings.ENDAOMENT_REDIRECT_URL

        self.http_session = requests.Session()
        self.http_session.headers["Content-Type"] = "application/json"

    def build_authorization_url(
        self, user_id: int, return_url: str | None = None
    ) -> str:
        """
        Build Endaoment OAuth authorization URL with PKCE and signed state.

        Args:
            user_id: ID of the authenticated user.
            return_url: URL to redirect after OAuth completion.

        Returns:
            Full authorization URL for redirecting the user.
        """
        session = self._create_session()
        code_verifier = generate_token(48)

        # Build state data with `code_verifier` embedded
        state_data = {"user_id": user_id, "code_verifier": code_verifier}
        if self.is_valid_redirect_url(return_url):
            state_data["return_url"] = return_url

        state = signing.dumps(state_data)

        url, _ = session.create_authorization_url(
            f"{self.auth_url}/auth",
            redirect_uri=self.redirect_url,
            scope="accounts offline_access openid profile transactions",
            state=state,
            code_verifier=code_verifier,
            prompt="login consent",
        )
        return url

    def validate_state(self, state: str) -> dict:
        """
        Validate and decode the signed state token.

        Args:
            state: Signed state token from callback.

        Returns:
            Dict with `user_id`, `code_verifier`, and `return_url` (optional).

        Raises:
            signing.BadSignature: If state is invalid or expired
        """
        return signing.loads(state, max_age=600)

    def fetch_token(self, code: str, code_verifier: str) -> TokenResponse:
        """
        Exchange authorization code for tokens.
        """
        session = self._create_session()
        token = session.fetch_token(
            f"{self.auth_url}/token",
            grant_type="authorization_code",
            code=code,
            redirect_uri=self.redirect_url,
            code_verifier=code_verifier,
            timeout=REQUEST_TIMEOUT,
        )
        return TokenResponse(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_in=token.get("expires_in", 3600),
            id_token=token.get("id_token"),
            token_type=token.get("token_type", "Bearer"),
        )

    def refresh_access_token(self, refresh_token: str) -> TokenResponse:
        """
        Refresh an expired access token.
        """
        session = self._create_session()
        token = session.refresh_token(
            f"{self.auth_url}/token",
            refresh_token=refresh_token,
            timeout=REQUEST_TIMEOUT,
        )
        return TokenResponse(
            access_token=token["access_token"],
            refresh_token=token.get("refresh_token"),
            expires_in=token.get("expires_in", 3600),
            id_token=token.get("id_token"),
        )

    def _create_session(self) -> OAuth2Session:
        """
        Create a new OAuth2Session with PKCE support.
        """
        return OAuth2Session(
            client_id=self.client_id,
            client_secret=self.client_secret,
            code_challenge_method="S256",
        )

    def _do_request(self, method: str, path: str, access_token: str | None, **kwargs):
        response = self.http_session.request(
            method,
            f"{self.api_url}{path}",
            headers={"Authorization": f"Bearer {access_token}"} if access_token else {},
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def get_user_funds(self, access_token: str) -> list:
        """
        Fetch the authenticated user's DAFs from Endaoment.

        See: https://docs.endaoment.org/developers/api/funds/get-all-funds-managed-by-the-authenticated-user
        """
        if not access_token:
            raise ValueError("access_token is required")

        return self._do_request("GET", "/v1/funds/mine", access_token)

    def get_fund_by_id(self, access_token: str, fund_id: str) -> dict | None:
        """
        Fetch a specific fund by ID.

        See: https://docs.endaoment.org/developers/api/funds/get-fund-by-id
        """
        if not access_token:
            raise ValueError("access_token is required")

        try:
            return self._do_request("GET", f"/v1/funds/{fund_id}", access_token)
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                logger.warning(f"Fund with ID {fund_id} not found: {e}")
                return None
            else:
                raise

    def create_async_grant(
        self,
        access_token: str,
        origin_fund_id: str,
        destination_org_id: str,
        amount_in_cents: int,
        purpose: str,
    ) -> dict:
        """
        Create an async grant request from a fund (DAF) to an organization.

        See: https://docs.endaoment.org/developers/api/transfers/create-an-async-grant-request
        """
        if not access_token:
            raise ValueError("access_token is required")

        return self._do_request(
            "POST",
            "/v1/transfers/async-grants",
            access_token,
            json={
                "destinationOrgId": destination_org_id,
                "idempotencyKey": uuid.uuid4().hex,
                "originFundId": origin_fund_id,
                "purpose": purpose,
                "requestedAmount": str(amount_in_cents),
            },
        )

    def create_async_entity_transfer(
        self,
        access_token: str,
        origin_fund_id: str,
        destination_fund_id: str,
        amount_in_cents: int,
        purpose: str,
    ) -> dict:
        """
        Create an async entity transfer request from a fund (DAF) to another fund.

        See: https://docs.endaoment.org/developers/api/transfer/create-an-async-entity-transfer-request
        """
        if not access_token:
            raise ValueError("access_token is required")

        return self._do_request(
            "POST",
            "/v1/transfers/async-entity-transfers",
            access_token,
            json={
                "destinationFundId": destination_fund_id,
                "idempotencyKey": uuid.uuid4().hex,
                "originFundId": origin_fund_id,
                "purpose": purpose,
                "requestedAmount": str(amount_in_cents),
            },
        )

    @staticmethod
    def is_valid_redirect_url(url: str | None) -> bool:
        """
        Validate redirect URL against CORS whitelist.
        """
        if not url:
            return False
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}" in settings.CORS_ORIGIN_WHITELIST
