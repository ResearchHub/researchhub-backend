"""Expert Finder outreach mailbox (Connect Gmail) API views."""

import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIPermission
from research_ai.services.outreach.gmail_oauth import (
    GmailMailboxNotAllowedError,
    GmailOAuthConfigError,
    GmailOAuthError,
    GmailOAuthRedirectUriError,
    GmailOAuthService,
)
from user.permissions import IsModerator, UserIsEditor

logger = logging.getLogger(__name__)

_EDITOR_PERMISSIONS = [
    IsAuthenticated,
    ResearchAIPermission,
    UserIsEditor | IsModerator,
]


class OutreachMailboxView(APIView):
    """
    GET ``/expert-finder/mailbox/`` — connection status.
    DELETE ``/expert-finder/mailbox/`` — disconnect / revoke.
    """

    permission_classes = _EDITOR_PERMISSIONS

    def dispatch(self, request, *args, **kwargs):
        self.gmail_oauth_service = kwargs.pop(
            "gmail_oauth_service", GmailOAuthService()
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        return Response(self.gmail_oauth_service.get_connection_status(request.user))

    def delete(self, request: Request) -> Response:
        return Response(self.gmail_oauth_service.disconnect(request.user))


class OutreachMailboxConnectView(APIView):
    """
    GET ``/expert-finder/mailbox/connect/`` — FE helper: client_id, scopes, redirect_uri.
    POST ``/expert-finder/mailbox/connect/`` — exchange Google auth code for mailbox.
    """

    permission_classes = _EDITOR_PERMISSIONS

    def dispatch(self, request, *args, **kwargs):
        self.gmail_oauth_service = kwargs.pop(
            "gmail_oauth_service", GmailOAuthService()
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        try:
            return Response(self.gmail_oauth_service.get_connect_params())
        except GmailOAuthConfigError:
            return Response(
                {"detail": "Google OAuth not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception("Failed to load Gmail outreach connect params")
            return Response(
                {"detail": "Failed to initiate Gmail connection"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def post(self, request: Request) -> Response:
        code = (request.data.get("code") or "").strip()
        redirect_uri = (request.data.get("redirect_uri") or "").strip()
        if not code or not redirect_uri:
            return Response(
                {"detail": "code and redirect_uri are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = self.gmail_oauth_service.connect_with_code(
                request.user, code=code, redirect_uri=redirect_uri
            )
            return Response(payload)
        except GmailOAuthRedirectUriError:
            return Response(
                {"detail": "Invalid redirect_uri"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except GmailMailboxNotAllowedError as exc:
            return Response(
                {
                    "detail": (
                        "Only personal @gmail.com / @googlemail.com mailboxes "
                        "are allowed for outreach"
                    ),
                    "email": exc.email,
                    "code": "mailbox_not_allowed",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except GmailOAuthConfigError:
            return Response(
                {"detail": "Google OAuth not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except GmailOAuthError as exc:
            return Response(
                {"detail": str(exc) or "Gmail connection failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("Gmail outreach connect code exchange failed")
            return Response(
                {"detail": "Gmail connection failed"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
