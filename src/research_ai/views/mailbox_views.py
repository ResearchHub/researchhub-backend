"""Expert Finder outreach mailbox (Connect Gmail) API views."""

import logging

from django.conf import settings
from django.shortcuts import redirect
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.permissions import ResearchAIPermission
from research_ai.services.outreach.gmail_oauth import (
    GmailOAuthConfigError,
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
    GET ``/expert-finder/mailbox/connect/`` — start Google OAuth for Gmail send.
    """

    permission_classes = _EDITOR_PERMISSIONS

    def dispatch(self, request, *args, **kwargs):
        self.gmail_oauth_service = kwargs.pop(
            "gmail_oauth_service", GmailOAuthService()
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request) -> Response:
        try:
            return_url = request.query_params.get("return_url")
            payload = self.gmail_oauth_service.build_auth_url(
                request.user.id, return_url
            )
            return Response(payload)
        except GmailOAuthConfigError:
            return Response(
                {"detail": "Google OAuth not configured"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception:
            logger.exception("Failed to initiate Gmail outreach OAuth")
            return Response(
                {"detail": "Failed to initiate Gmail connection"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class OutreachMailboxCallbackView(APIView):
    """
    GET ``/expert-finder/mailbox/callback/`` — Google OAuth redirect handler.

    Unauthenticated: browser lands here from Google; user is bound via signed state.
    """

    permission_classes = [AllowAny]

    def dispatch(self, request, *args, **kwargs):
        self.gmail_oauth_service = kwargs.pop(
            "gmail_oauth_service", GmailOAuthService()
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request: Request):
        try:
            error = request.query_params.get("error")
            code = request.query_params.get("code")
            if error or not code:
                return redirect(
                    self.gmail_oauth_service.get_redirect_url(error="error")
                )

            state = request.query_params.get("state", "")
            return redirect(
                self.gmail_oauth_service.process_callback(code=code, state=state)
            )
        except Exception:
            logger.exception("Gmail outreach OAuth callback view failed")
            fallback = (
                getattr(settings, "GMAIL_OUTREACH_FRONTEND_RETURN_URL", None)
                or settings.BASE_FRONTEND_URL
            )
            sep = "&" if "?" in fallback else "?"
            return redirect(f"{fallback}{sep}gmail=error")
