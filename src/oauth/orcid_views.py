import base64
import json
import logging
from http import HTTPStatus
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import HttpResponseRedirect
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth.tasks import sync_orcid_publications
from utils.orcid import (
    OrcidAccountConflictError,
    OrcidAuthenticationError,
    OrcidServiceError,
    OrcidTokenExpiredError,
    create_or_update_orcid_account,
    exchange_orcid_code_for_tokens,
    get_user_orcid_credentials,
)
from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)
User = get_user_model()


class OrcidErrorMessages:
    ACCOUNT_CONFLICT = "This ORCID account has already been linked to another user."
    AUTHENTICATION_FAILED = "ORCID authorization failed. Please try again."
    TOKEN_EXPIRED = (
        "Your ORCID access token has expired. Please reconnect your ORCID account."
    )
    CONNECTION_FAILED = "ORCID connection failed. Please try again."
    SERVICE_ERRORS = {
        HTTPStatus.FORBIDDEN: (
            "Access to ORCID was denied. Please check your ORCID permissions."
        ),
        HTTPStatus.INTERNAL_SERVER_ERROR: (
            "ORCID service is temporarily unavailable. Please try again later."
        ),
    }
    SESSION_ERRORS = {
        "missing_authorization_code": (
            "ORCID authorization was cancelled or failed. Please try again."
        ),
        "missing_session_state": (
            "ORCID authorization session expired. Please try again."
        ),
        "invalid_session_state": (
            "ORCID authorization session is invalid. Please try again."
        ),
        "missing_user_id": (
            "ORCID authorization session is incomplete. Please try again."
        ),
        "user_not_found": (
            "Your account session has expired. Please log in and try again."
        ),
    }


def build_redirect_url_with_params(base_url: str, **query_params) -> str:
    parsed_url = urlparse(base_url)
    existing_params = parse_qs(parsed_url.query)
    for param_name, param_value in query_params.items():
        existing_params[param_name] = [str(param_value)]
    updated_query = urlencode(existing_params, doseq=True)
    return urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            updated_query,
            parsed_url.fragment,
        )
    )


def create_encoded_oauth_state(user_id: int, return_url: str = None) -> str:
    state_data = {"user_id": user_id}
    if return_url:
        state_data["return_to"] = return_url

    state_json = json.dumps(state_data, separators=(",", ":"))
    return base64.b64encode(state_json.encode("utf-8")).decode("utf-8")


def decode_oauth_state_parameter(encoded_state: str) -> dict:
    try:
        decoded_state_bytes = base64.b64decode(encoded_state)
        state_json_string = decoded_state_bytes.decode("utf-8")
        return json.loads(state_json_string)
    except (ValueError, json.JSONDecodeError):
        return {}


def build_orcid_authorization_url(user_id: int, return_url: str = None) -> str:
    orcid_base_url = getattr(settings, "ORCID_BASE_URL", "https://orcid.org")
    authorization_endpoint = f"{orcid_base_url}/oauth/authorize"
    return build_redirect_url_with_params(
        authorization_endpoint,
        client_id=settings.ORCID_CLIENT_ID,
        response_type="code",
        scope="/authenticate",
        redirect_uri=settings.ORCID_REDIRECT_URL,
        state=create_encoded_oauth_state(user_id, return_url),
    )


def is_orcid_token_valid(orcid_user_id: str, access_token: str) -> bool:
    try:
        orcid_profile_url = f"https://pub.orcid.org/v3.0/{orcid_user_id}"
        request_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.orcid+json",
        }

        with retryable_requests_session() as http_session:
            response = http_session.get(
                orcid_profile_url, headers=request_headers, timeout=10
            )

            if response.status_code != HTTPStatus.OK:
                return False

            response_content_type = response.headers.get("content-type", "")
            return response_content_type.startswith(
                "application/json"
            ) or response_content_type.startswith("application/vnd.orcid+json")
    except Exception:
        return False


def find_user_by_id(user_id: int):
    return User.objects.filter(id=user_id).first()


def get_error_message_for_service_exception(exception) -> str:
    if not hasattr(exception, "response") or exception.response is None:
        return OrcidErrorMessages.CONNECTION_FAILED

    return OrcidErrorMessages.SERVICE_ERRORS.get(
        exception.response.status_code, OrcidErrorMessages.CONNECTION_FAILED
    )


def create_session_error_redirect(
    error_type: str, return_url=None, session_return_url=None
):
    error_message = OrcidErrorMessages.SESSION_ERRORS[error_type]
    return create_error_redirect(return_url, session_return_url, error_message)


def handle_orcid_authorization_flow(
    current_user, authorization_code: str, return_url: str
):
    try:
        with transaction.atomic():
            orcid_token_data = exchange_orcid_code_for_tokens(authorization_code)
            create_or_update_orcid_account(current_user, orcid_token_data)

        sync_orcid_publications.delay(current_user.id)

        success_redirect_url = return_url or settings.BASE_FRONTEND_URL
        return HttpResponseRedirect(
            build_redirect_url_with_params(
                success_redirect_url, orcid_sync="ok", user_id=current_user.id
            )
        )

    except OrcidAccountConflictError:
        return create_error_redirect(
            return_url, None, OrcidErrorMessages.ACCOUNT_CONFLICT
        )
    except OrcidAuthenticationError:
        return create_error_redirect(
            return_url, None, OrcidErrorMessages.AUTHENTICATION_FAILED
        )
    except OrcidTokenExpiredError:
        return create_error_redirect(return_url, None, OrcidErrorMessages.TOKEN_EXPIRED)
    except OrcidServiceError:
        return create_error_redirect(
            return_url, None, OrcidErrorMessages.CONNECTION_FAILED
        )

    except Exception as unexpected_error:
        logger.error(
            f"ORCID callback error for user {current_user.id}: {unexpected_error}"
        )
        error_message = get_error_message_for_service_exception(unexpected_error)
        return create_error_redirect(return_url, None, error_message)


def create_error_redirect(return_url, session_return_url, error_message):
    final_redirect_url = return_url or session_return_url or settings.BASE_FRONTEND_URL
    return HttpResponseRedirect(
        build_redirect_url_with_params(
            final_redirect_url, orcid_sync="fail", error=error_message
        )
    )


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            orcid_auth_url = build_orcid_authorization_url(
                user_id=request.user.id, return_url=request.data.get("return_to")
            )
            return Response({"auth_url": orcid_auth_url, "user_id": request.user.id})
        except Exception as url_generation_error:
            logger.error(f"Error generating ORCID auth URL: {url_generation_error}")
            return Response({"error": str(url_generation_error)}, status=500)


class OrcidCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_orcid_account, user_orcid_token = get_user_orcid_credentials(
            request.user, auto_refresh=True
        )

        if not all([user_orcid_account, user_orcid_token]) or not getattr(
            user_orcid_token, "token", None
        ):
            return Response({"connected": False, "needs_reauth": True})

        token_is_valid = is_orcid_token_valid(
            user_orcid_account.uid, user_orcid_token.token
        )
        return Response(
            {"connected": token_is_valid, "needs_reauth": not token_is_valid}
        )


class OrcidCallbackView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        oauth_authorization_code = request.GET.get("code")
        oauth_state_parameter = request.GET.get("state")

        if not oauth_authorization_code:
            return create_session_error_redirect("missing_authorization_code")

        if not oauth_state_parameter:
            return create_session_error_redirect("missing_session_state")

        decoded_oauth_state = decode_oauth_state_parameter(oauth_state_parameter)
        if not decoded_oauth_state:
            return create_session_error_redirect("invalid_session_state")

        user_id_from_state = decoded_oauth_state.get("user_id")
        return_url_from_state = decoded_oauth_state.get("return_to")

        if not user_id_from_state:
            return create_session_error_redirect(
                "missing_user_id", return_url_from_state
            )

        authenticated_user = find_user_by_id(user_id_from_state)
        if not authenticated_user:
            return create_session_error_redirect(
                "user_not_found", return_url_from_state
            )

        return handle_orcid_authorization_flow(
            authenticated_user, oauth_authorization_code, return_url_from_state
        )


class OrcidSyncView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        sync_orcid_publications.delay(request.user.id)
        return Response({"ok": True})
