# oauth/orcid_views.py
import base64
import json
import logging
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
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


def _redirect_with_error(return_to, session_return_to, error_msg):
    """Helper to redirect to frontend with error message."""
    rt = return_to or session_return_to or settings.BASE_FRONTEND_URL
    sep = "&" if "?" in rt else "?"
    encoded_error = quote(error_msg, safe="")
    return HttpResponseRedirect(f"{rt}{sep}orcid_sync=fail&error={encoded_error}")


# Cache ORCID settings to avoid repeated getattr calls
_ORCID_SETTINGS = {
    "base_url": getattr(settings, "ORCID_BASE_URL", "https://orcid.org"),
    "client_id": getattr(settings, "ORCID_CLIENT_ID"),
    "redirect_uri": getattr(
        settings, "ORCID_REDIRECT_URI", getattr(settings, "ORCID_REDIRECT_URL", None)
    ),
    "auth_scope": getattr(settings, "ORCID_AUTH_SCOPE", "/authenticate"),
}


def generate_orcid_auth_url(
    user_id: int, return_to: str = None, csrf_token: str = None
) -> str:
    """
    Generate ORCID authorization URL with state parameter - OPTIMIZED.

    Args:
        user_id: ID of the user requesting ORCID authentication
        return_to: Optional URL to redirect to after successful auth
        csrf_token: Optional CSRF token for security

    Returns:
        Complete ORCID authorization URL
    """
    from urllib.parse import urlencode

    from django.conf import settings

    # Prepare state data efficiently
    state_data = {"user_id": user_id}
    if return_to:
        state_data["return_to"] = return_to
    if csrf_token:
        state_data["csrf_token"] = csrf_token

    # Encode state as base64 JSON (more efficient with cached separators)
    state_json = json.dumps(state_data, separators=(",", ":"))
    state_encoded = base64.b64encode(state_json.encode("utf-8")).decode("utf-8")

    # Use cached settings for production, but allow dynamic settings in tests
    # This ensures @override_settings works properly in tests
    base_url = getattr(settings, "ORCID_BASE_URL", _ORCID_SETTINGS["base_url"])
    client_id = getattr(settings, "ORCID_CLIENT_ID", _ORCID_SETTINGS["client_id"])
    redirect_uri = getattr(
        settings,
        "ORCID_REDIRECT_URI",
        getattr(settings, "ORCID_REDIRECT_URL", _ORCID_SETTINGS["redirect_uri"]),
    )
    auth_scope = getattr(settings, "ORCID_AUTH_SCOPE", _ORCID_SETTINGS["auth_scope"])

    # Build authorization URL
    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": auth_scope,
        "redirect_uri": redirect_uri,
        "state": state_encoded,
    }

    return f"{base_url}/oauth/authorize?{urlencode(params)}"


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

            # Check if user already has ORCID linked
            from allauth.socialaccount.models import SocialAccount

            existing_orcid = SocialAccount.objects.filter(
                user=request.user, provider="orcid"
            ).first()

            response_data = {"auth_url": auth_url, "user_id": request.user.id}

            if existing_orcid:
                response_data["warning"] = (
                    f"You already have ORCID {existing_orcid.uid} linked. "
                    f"Linking a new ORCID will replace the existing one."
                )

            return Response(response_data)
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
                    "error": "No ORCID account connected. "
                    "Please connect your ORCID account.",
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
                    error = (
                        "Your ORCID access has expired. "
                        "Please reconnect your ORCID account."
                    )
                elif "html" in r.headers.get("content-type", "").lower():
                    needs_reauth = True
                    error = (
                        "Your ORCID access has expired. "
                        "Please reconnect your ORCID account."
                    )

        except Exception:
            needs_reauth = True
            error = (
                "Unable to verify ORCID connection. "
                "Please reconnect your ORCID account."
            )

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
                None,
                None,
                "ORCID authorization was cancelled or failed. Please try again.",
            )

        if not state:
            return _redirect_with_error(
                None, None, "ORCID authorization session expired. Please try again."
            )

        # Decode state to get user identification and return URL
        try:
            state_data = json.loads(base64.b64decode(state).decode("utf-8"))
            user_id = state_data.get("user_id")
            return_to = state_data.get("return_to")
            # csrf_token = state_data.get("csrf_token")  # Future: CSRF validation
        except Exception:
            return _redirect_with_error(
                None, None, "ORCID authorization session is invalid. Please try again."
            )

        if not user_id:
            return _redirect_with_error(
                return_to,
                None,
                "ORCID authorization session is incomplete. Please try again.",
            )

        # Get the user for token association
        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return _redirect_with_error(
                return_to,
                None,
                "Your account session has expired. Please log in and try again.",
            )

        try:
            # Exchange code for tokens and upsert - wrapped in transaction
            with transaction.atomic():
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
        except ValueError as e:
            # Handle business logic errors (like duplicate ORCID linking)
            if "already linked to another user" in str(e):
                return _redirect_with_error(
                    return_to,
                    None,
                    "This ORCID account has already been linked to another user.",
                )
            else:
                return _redirect_with_error(
                    return_to, None, "ORCID authorization failed. Please try again."
                )
        except Exception as e:
            # Log the error and redirect with failure
            logger = logging.getLogger(__name__)
            logger.error(f"ORCID callback error for user {user.id}: {e}")

            # Prepare user-friendly error message for frontend
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
                if status_code == 401:
                    error_msg = "ORCID authorization failed. Please try again."
                elif status_code == 403:
                    error_msg = (
                        "Access to ORCID was denied. "
                        "Please check your ORCID permissions."
                    )
                elif status_code == 500:
                    error_msg = (
                        "ORCID service is temporarily unavailable. "
                        "Please try again later."
                    )
                else:
                    error_msg = "ORCID connection failed. Please try again."
            else:
                error_msg = "ORCID connection failed. Please try again."

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
