# oauth/orcid_views.py
import base64
import json
import logging
from urllib.parse import quote

from django.conf import settings
from django.http import HttpResponseRedirect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth.tasks import sync_orcid_for_user_task
from utils.orcid import (
    exchange_code_for_token,
    get_orcid_account_and_token,
    upsert_orcid_token,
)


def _normalize_doi(doi: str) -> str:
    """Deprecated: moved to `oauth.services`. Kept for backward compat."""
    if not doi:
        return doi
    return doi.replace("https://doi.org/", "").strip().lower()


def _redirect_with_error(return_to, session_return_to, error_msg):
    """Helper to redirect to frontend with error message."""
    rt = return_to or session_return_to or settings.BASE_FRONTEND_URL
    sep = "&" if "?" in rt else "?"
    encoded_error = quote(error_msg, safe="")
    return HttpResponseRedirect(f"{rt}{sep}orcid_sync=fail&error={encoded_error}")


def generate_orcid_auth_url(
    user_id: int, return_to: str = None, csrf_token: str = None
) -> str:
    """
    Generate ORCID authorization URL with state parameter containing user ID.

    Args:
        user_id: ID of the user requesting ORCID authentication
        return_to: Optional URL to redirect to after successful auth
        csrf_token: Optional CSRF token for security

    Returns:
        Complete ORCID authorization URL
    """
    from urllib.parse import urlencode

    # Prepare state data
    state_data = {"user_id": user_id}
    if return_to:
        state_data["return_to"] = return_to
    if csrf_token:
        state_data["csrf_token"] = csrf_token

    # Encode state as base64 JSON
    state_json = json.dumps(state_data)
    state_encoded = base64.b64encode(state_json.encode("utf-8")).decode("utf-8")

    # Build authorization URL
    orcid_base = getattr(settings, "ORCID_BASE_URL", "https://orcid.org")
    redirect_uri = getattr(
        settings, "ORCID_REDIRECT_URI", getattr(settings, "ORCID_REDIRECT_URL", None)
    )
    client_id = getattr(settings, "ORCID_CLIENT_ID")
    # Use authenticate scope for OAuth login, or configured scope
    scope = getattr(settings, "ORCID_AUTH_SCOPE", "/authenticate")

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": scope,
        "redirect_uri": redirect_uri,
        "state": state_encoded,
    }

    return f"{orcid_base}/oauth/authorize?{urlencode(params)}"


class OrcidAuthUrlView(APIView):
    """
    Generate ORCID authorization URL for direct callbacks.

    This endpoint generates a properly formatted ORCID authorization URL
    that includes the authenticated user's ID in the state parameter.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Generate ORCID authorization URL with user identification.

        Query parameters:
            - return_to: Optional URL to redirect to after successful auth

        Response:
            {
                "auth_url": "https://orcid.org/oauth/authorize?...",
                "user_id": 123
            }
        """
        # Explicit authentication check
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required"}, status=401)

        return_to = request.GET.get("return_to")
        csrf_token = request.session.get("csrf_token")  # Optional CSRF

        try:
            auth_url = generate_orcid_auth_url(
                user_id=request.user.id, return_to=return_to, csrf_token=csrf_token
            )

            return Response({"auth_url": auth_url, "user_id": request.user.id})
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Error generating ORCID auth URL: {e}")
            return Response(
                {"error": f"Failed to generate auth URL: {str(e)}"}, status=500
            )


class OrcidCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Report whether the current user has a valid ORCID access token.

        Attempts an auto-refresh and tests token validity against ORCID API.
        Response: {
            "authenticated": bool,
            "orcid_id": str|null,
            "needs_reauth": bool,
            "error": str|null
        }
        """
        account, token = get_orcid_account_and_token(request.user, auto_refresh=True)

        if not (account and token and token.token):
            return Response(
                {
                    "authenticated": False,
                    "orcid_id": None,
                    "needs_reauth": True,
                    "error": "No ORCID token found",
                }
            )

        # Test token validity by trying to access the ORCID record
        orcid_id = account.uid
        needs_reauth = False
        error = None

        try:
            from utils.retryable_requests import retryable_requests_session

            test_url = f"https://pub.orcid.org/v3.0/{orcid_id}"
            headers = {
                "Authorization": f"Bearer {token.token}",
                "Accept": "application/vnd.orcid+json",
            }

            with retryable_requests_session() as session:
                r = session.get(test_url, headers=headers, timeout=10)

                if r.status_code != 200:
                    needs_reauth = True
                    error = f"ORCID API returned status {r.status_code}"
                elif "html" in r.headers.get("content-type", "").lower():
                    needs_reauth = True
                    error = "Token appears to be invalid - ORCID returning login page"

        except Exception as e:
            needs_reauth = True
            error = f"Failed to validate token: {str(e)}"

        return Response(
            {
                "authenticated": not needs_reauth,
                "orcid_id": orcid_id,
                "needs_reauth": needs_reauth,
                "error": error,
            }
        )


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        """
        Handle the ORCID OAuth callback directly from ORCID.

        This endpoint receives direct callbacks from ORCID after user authorization.
        The state parameter contains user identification and optional return URL.

        Expected state format (base64-encoded JSON):
        {
            "user_id": 123,  # Required: User ID for token association
            "return_to": "http://...",  # Optional: Redirect URL after success
            "csrf_token": "..."  # Optional: CSRF protection
        }

        On success, triggers a background sync and redirects with `orcid_sync=ok`.
        On failure, redirects with `orcid_sync=fail`.
        """
        code = request.GET.get("code")
        state = request.GET.get("state")

        if not code:
            return _redirect_with_error(
                None, None, "No authorization code received from ORCID"
            )

        if not state:
            return _redirect_with_error(None, None, "No state parameter provided")

        # Decode state to get user identification and return URL
        try:
            state_data = json.loads(base64.b64decode(state).decode("utf-8"))
            user_id = state_data.get("user_id")
            return_to = state_data.get("return_to")
            # csrf_token = state_data.get("csrf_token")  # Future: CSRF validation
        except Exception as e:
            return _redirect_with_error(
                None, None, f"Invalid state parameter: {str(e)}"
            )

        if not user_id:
            return _redirect_with_error(
                return_to, None, "Missing user identification in state"
            )

        # Get the user for token association
        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return _redirect_with_error(
                return_to, None, f"User with ID {user_id} not found"
            )

        try:
            # Exchange code for tokens using the identified user
            payload = exchange_code_for_token(code)
            upsert_orcid_token(user, payload)

            # Enqueue background sync for the identified user
            sync_orcid_for_user_task.delay(user.id)

            # Determine redirect URL
            redirect_url = return_to or settings.BASE_FRONTEND_URL
            sep = "&" if "?" in redirect_url else "?"

            # Add success parameter and user context
            success_params = f"orcid_sync=ok&user_id={user.id}"
            return HttpResponseRedirect(f"{redirect_url}{sep}{success_params}")
        except Exception as e:
            # Log the error and redirect with failure
            logger = logging.getLogger(__name__)
            logger.error(f"ORCID callback error for user {user.id}: {e}")

            # Prepare error message for frontend
            error_msg = str(e)
            if hasattr(e, "response") and e.response is not None:
                try:
                    error_detail = e.response.json().get("error_description", str(e))
                except Exception:
                    error_detail = f"HTTP {e.response.status_code}: {e.response.reason}"
                error_msg = error_detail

            return _redirect_with_error(return_to, None, error_msg)


class OrcidSyncView(APIView):
    """
    Manual re-sync endpoint used by the "Sync Authorship" UI action.

    Invokes the same syncing routine as the OAuth callback without re-auth.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        sync_orcid_for_user_task.delay(request.user.id)
        return Response({"ok": True})
