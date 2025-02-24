import base64
import hashlib

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from utils.permissions import CreateOrUpdateIfAllowed



# TODO: https://www.notion.so/researchhub/Make-a-generic-class-to-handle-uploading-files-to-S3-88c40abfbbe04a03aa00f82f9ab7c345
class CommentFileUpload(viewsets.ViewSet):
    permission_classes = [IsAuthenticated & CreateOrUpdateIfAllowed]
    ALLOWED_EXTENSIONS = (
        "gif",
        "jpeg",
        "pdf",
        "png",
        "svg",
        "tiff",
        "webp",
        "mp4",
        "webm",
        "ogg",
    )

    def create(self, request):
        if request.FILES:
            data = request.FILES["upload"]
            content_type = data.content_type.split("/")[1]

            # Extension check
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response("Invalid extension", status=400)

            # Special characters check
            if any(not c.isalnum() for c in content_type):
                return Response("Special Characters", status=400)

            content = data.read()
            bucket_directory = f"comment_files/{content_type}"
            checksum = hashlib.md5(content).hexdigest()
            path = f"{bucket_directory}/{checksum}.{content_type}"

            if default_storage.exists(path):
                url = default_storage.url(path)
                res_status = status.HTTP_200_OK
            else:
                file_path = default_storage.save(path, data)
                url = default_storage.url(file_path)
                res_status = status.HTTP_201_CREATED

            url = url.split("?AWSAccessKeyId")[0]
            return Response({"url": url}, status=res_status)
        else:
            content_type = request.data.get("content_type")
            if content_type.lower() not in self.ALLOWED_EXTENSIONS:
                return Response("Invalid extension", status=400)

            if any(not c.isalnum() for c in content_type):
                return Response("Special Characters", status=400)

            _, base64_content = request.data.get("content").split(";base64,")
            base64_content = base64_content.encode()

            bucket_directory = f"comment_files/{content_type}"
            checksum = hashlib.md5(base64_content).hexdigest()
            path = f"{bucket_directory}/{checksum}.{content_type}"
            file_data = base64.b64decode(base64_content)
            data = ContentFile(file_data)

            if default_storage.exists(path):
                url = default_storage.url(path)
                res_status = status.HTTP_200_OK
            else:
                file_path = default_storage.save(path, data)
                url = default_storage.url(file_path)
                res_status = status.HTTP_201_CREATED

            url = url.split("?AWSAccessKeyId")[0]
            return Response(url, status=res_status)
