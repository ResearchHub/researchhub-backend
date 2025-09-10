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
    create_or_update_orcid_account,
    exchange_orcid_code_for_tokens,
    get_user_orcid_credentials,
)


def redirect_with_error(return_to, session_return_to, error_msg):
    rt = return_to or session_return_to or settings.BASE_FRONTEND_URL
    sep = "&" if "?" in rt else "?"
    encoded_error = quote(error_msg, safe="")
    return HttpResponseRedirect(f"{rt}{sep}orcid_sync=fail&error={encoded_error}")


def build_orcid_auth_url(user_id: int, return_to: str = None) -> str:
    from urllib.parse import urlencode

    state_data = {"user_id": user_id}
    if return_to:
        state_data["return_to"] = return_to

    state_json = json.dumps(state_data, separators=(",", ":"))
    state_encoded = base64.b64encode(state_json.encode("utf-8")).decode("utf-8")

    base_url = getattr(settings, "ORCID_BASE_URL", "https://orcid.org")
    client_id = getattr(settings, "ORCID_CLIENT_ID")
    redirect_uri = getattr(settings, "ORCID_REDIRECT_URL")
    auth_scope = "/authenticate"

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": auth_scope,
        "redirect_uri": redirect_uri,
        "state": state_encoded,
    }

    return f"{base_url}/oauth/authorize?{urlencode(params)}"


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            auth_url = build_orcid_auth_url(
                user_id=request.user.id, return_to=request.data.get("return_to")
            )
            return Response({"auth_url": auth_url, "user_id": request.user.id})
        except Exception as e:
            logging.getLogger(__name__).error(f"Error generating ORCID auth URL: {e}")
            return Response(
                {"error": f"Failed to generate auth URL: {str(e)}"}, status=500
            )


class OrcidCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        account, token = get_user_orcid_credentials(request.user, auto_refresh=True)

        if not (account and token and token.token):
            return Response({"authenticated": False, "needs_reauth": True})

        try:
            from utils.retryable_requests import retryable_requests_session

            test_url = f"https://pub.orcid.org/v3.0/{account.uid}"
            headers = {
                "Authorization": f"Bearer {token.token}",
                "Accept": "application/vnd.orcid+json",
            }

            with retryable_requests_session() as session:
                r = session.get(test_url, headers=headers, timeout=10)

                if (
                    r.status_code != 200
                    or "html" in r.headers.get("content-type", "").lower()
                ):
                    return Response({"authenticated": False, "needs_reauth": True})

        except Exception:
            return Response({"authenticated": False, "needs_reauth": True})

        return Response({"authenticated": True, "needs_reauth": False})


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")

        if not code:
            return redirect_with_error(
                None,
                None,
                "ORCID authorization was cancelled or failed. Please try again.",
            )

        if not state:
            return redirect_with_error(
                None, None, "ORCID authorization session expired. Please try again."
            )

        try:
            state_data = json.loads(base64.b64decode(state).decode("utf-8"))
            user_id = state_data.get("user_id")
            return_to = state_data.get("return_to")
        except Exception:
            return redirect_with_error(
                None, None, "ORCID authorization session is invalid. Please try again."
            )

        if not user_id:
            return redirect_with_error(
                return_to,
                None,
                "ORCID authorization session is incomplete. Please try again.",
            )

        from django.contrib.auth import get_user_model

        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return redirect_with_error(
                return_to,
                None,
                "Your account session has expired. Please log in and try again.",
            )

        try:
            with transaction.atomic():
                payload = exchange_orcid_code_for_tokens(code)
                create_or_update_orcid_account(user, payload)

            sync_orcid_for_user_task.delay(user.id)

            redirect_url = return_to or settings.BASE_FRONTEND_URL
            sep = "&" if "?" in redirect_url else "?"
            success_params = f"orcid_sync=ok&user_id={user.id}"
            return HttpResponseRedirect(f"{redirect_url}{sep}{success_params}")
        except ValueError as e:
            if "already linked to another user" in str(e):
                return redirect_with_error(
                    return_to,
                    None,
                    "This ORCID account has already been linked to another user.",
                )
            else:
                return redirect_with_error(
                    return_to,
                    None,
                    "ORCID authorization failed. Please try again.",
                )
        except Exception as e:
            logging.getLogger(__name__).error(
                f"ORCID callback error for user {user.id}: {e}"
            )

            error_msg = "ORCID connection failed. Please try again."
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
                if status_code == 403:
                    error_msg = (
                        "Access to ORCID was denied. "
                        "Please check your ORCID permissions."
                    )
                elif status_code == 500:
                    error_msg = (
                        "ORCID service is temporarily unavailable. "
                        "Please try again later."
                    )

            return redirect_with_error(return_to, None, error_msg)


class OrcidSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sync_orcid_for_user_task.delay(request.user.id)
        return Response({"ok": True})
