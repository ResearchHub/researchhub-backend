from allauth.socialaccount.models import SocialApp
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from orcid.services.orcid_service import OrcidService


class OrcidConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.orcid_service = OrcidService()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request, *args, **kwargs) -> Response:
        try:
            return_url = request.data.get("return_url")
            auth_url = self.orcid_service.build_auth_url(request.user.id, return_url)
            return Response({"auth_url": auth_url})
        except SocialApp.DoesNotExist:
            return Response({"error": "ORCID not configured"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception:
            return Response({"error": "Failed to initiate ORCID connection"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
