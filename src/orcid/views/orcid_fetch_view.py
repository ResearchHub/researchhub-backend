from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from orcid.tasks import sync_orcid_task
from user.models import Author


class OrcidFetchView(APIView):
    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.sync_task = kwargs.pop("sync_task", sync_orcid_task)
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request) -> Response:
        """Trigger asynchronous ORCID data synchronization."""
        author = Author.objects.filter(user=request.user).first()
        if not author:
            return Response(
                {"error": "Author profile not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not author.is_orcid_connected:
            return Response(
                {"error": "ORCID not connected"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        self.sync_task.delay(author.id)
        return Response({"message": "ORCID sync started"})
