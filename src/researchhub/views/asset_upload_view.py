from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from researchhub.serializers.asset_upload_serializer import AssetUploadRequestSerializer
from researchhub.services.storage_service import S3StorageService
from utils.parsers import clean_filename


class AssetUploadView(APIView):
    """
    View for uploading assets into ResearchHub storage.
    """

    permission_classes = [IsAuthenticated]

    def dispatch(self, request, *args, **kwargs):
        self.storage_service = kwargs.pop("storage_service", S3StorageService())
        return super().dispatch(request, *args, **kwargs)

    def post(self, request: Request, *args, **kwargs) -> Response:
        """
        Creates a presigned URL for uploading an asset and returns it.
        """
        user = request.user
        data = request.data

        # Validate request data
        serializer = AssetUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        content_type = data.get("content_type")
        entity = data.get("entity")
        filename = clean_filename(data.get("filename"))

        presigned_url = self.storage_service.create_presigned_url(
            entity, filename, user.id, content_type
        )

        return Response(
            {
                "presigned_url": presigned_url.url,
                "object_key": presigned_url.object_key,
                "object_url": presigned_url.object_url,
            }
        )
