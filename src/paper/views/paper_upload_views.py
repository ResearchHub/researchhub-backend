from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from paper.serializers.paper_upload_serializer import PaperUploadSerializer
from paper.services.storage_service import StorageService


class PaperUploadView(APIView):
    """
    View for uploading papers.
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.storage_service = kwargs.pop("storage_service", StorageService())
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Creates a presigned URL for uploading a paper and returns it.
        """
        user = request.user
        data = request.data

        # Validate request data
        serializer = PaperUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        filename = data.get("filename")

        presigned_url = self.storage_service.create_presigned_url(filename, user.id)

        return Response(
            {
                "presigned_url": presigned_url.url,
                "object_key": presigned_url.object_key,
            }
        )
