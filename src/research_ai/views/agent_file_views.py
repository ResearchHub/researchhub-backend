"""API for files users attach to the notebook and assistant chats.

The bytes go from the browser straight to the private bucket:

1. ``POST files/`` with ``filename`` and ``size_bytes`` returns the file
   (``UPLOADING``) plus ``upload``: POST its ``fields``, then the file as
   ``file``, to its ``url`` as multipart form data.
2. ``POST files/<id>/complete/`` once S3 accepts it starts text extraction
   (``PROCESSING``).
3. Poll ``GET files/<id>/`` until ``READY`` (or ``FAILED`` with ``error``),
   then send the id in a chat message's ``file_ids``.

Files are private to their uploader: another user's file id is a 404. Access
is gated like the chats themselves.
"""

from django.http import Http404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from research_ai.models import AgentFile
from research_ai.permissions import ResearchAIBudgetPermission
from research_ai.serializers import AgentFileCreateSerializer
from research_ai.services.agent_files import (
    AgentFileError,
    AgentFileService,
    public_file,
)
from researchhub.services.private_storage_service import (
    PrivateStorageNotConfiguredError,
)

AGENT_FILE_PERMISSIONS = [IsAuthenticated, ResearchAIBudgetPermission]


def _get_file_or_404(service: AgentFileService, user, file_id: int) -> AgentFile:
    file = service.get_file(user, file_id)
    if file is None:
        raise Http404
    return file


def _error_response(error: AgentFileError, status_code: int) -> Response:
    return Response({"detail": str(error), "code": error.code}, status=status_code)


class AgentFileCreateView(APIView):
    """Start an upload."""

    permission_classes = AGENT_FILE_PERMISSIONS

    def post(self, request):
        serializer = AgentFileCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            file, upload = AgentFileService().create_upload(
                request.user, **serializer.validated_data
            )
        except AgentFileError as error:
            return _error_response(error, status.HTTP_400_BAD_REQUEST)
        except PrivateStorageNotConfiguredError:
            return Response(
                {
                    "detail": "File uploads are not available.",
                    "code": "uploads_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            {
                **public_file(file),
                "upload": {"url": upload.url, "fields": upload.fields},
            },
            status=status.HTTP_201_CREATED,
        )


class AgentFileDetailView(APIView):
    """Read a file's processing state, or remove it before it is sent."""

    permission_classes = AGENT_FILE_PERMISSIONS

    def get(self, request, file_id):
        service = AgentFileService()
        file = _get_file_or_404(service, request.user, file_id)
        return Response(public_file(service.refresh(file)))

    def delete(self, request, file_id):
        service = AgentFileService()
        file = _get_file_or_404(service, request.user, file_id)
        try:
            service.delete(file)
        except AgentFileError as error:
            return _error_response(error, status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AgentFileCompleteView(APIView):
    """Confirm the upload reached storage; idempotent."""

    permission_classes = AGENT_FILE_PERMISSIONS

    def post(self, request, file_id):
        service = AgentFileService()
        file = _get_file_or_404(service, request.user, file_id)
        try:
            file = service.complete_upload(file)
        except AgentFileError as error:
            return _error_response(error, status.HTTP_409_CONFLICT)
        return Response(public_file(file))


class AgentFileDownloadView(APIView):
    """A short-lived URL to open the stored file."""

    permission_classes = AGENT_FILE_PERMISSIONS

    def get(self, request, file_id):
        service = AgentFileService()
        file = _get_file_or_404(service, request.user, file_id)
        try:
            url = service.download_url(file)
        except AgentFileError as error:
            return _error_response(error, status.HTTP_409_CONFLICT)
        return Response({"url": url})
