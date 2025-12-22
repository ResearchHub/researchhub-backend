import logging

from allauth.socialaccount.models import SocialApp
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from orcid.services import OrcidConnectService

logger = logging.getLogger(__name__)


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.orcid_service = kwargs.pop("orcid_service", OrcidConnectService())
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request) -> Response:
        """Initiate ORCID OAuth flow by returning the authorization URL."""
        try:
            return_url = request.data.get("return_url")
            auth_url = self.orcid_service.build_auth_url(request.user.id, return_url)
            return Response({"auth_url": auth_url})
        except SocialApp.DoesNotExist:
            return Response({"error": "ORCID not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            logger.exception("Failed to initiate ORCID connection")
            return Response({"error": "Failed to initiate ORCID connection"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
