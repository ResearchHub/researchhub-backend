import os
import unicodedata
import uuid
from urllib.parse import quote

from django.conf import settings

from researchhub.services.storage_service import (
    SUPPORTED_CONTENT_TYPES,
    SUPPORTED_ENTITIES,
    PresignedUrl,
    StorageService,
)


class LocalStorageService(StorageService):
    """
    Service for local filesystem storage that mimics S3 behavior.
    Uses Django's default storage backend to handle files locally.
    """

    def create_presigned_url(
        self,
        entity: str,
        filename: str,
        user_id: str,
        content_type: str,
        valid_for_min: int = 2,
    ) -> PresignedUrl:
        """
        Create a "presigned URL" for local storage.
        Returns URLs that point to local media files.
        """

        if entity not in SUPPORTED_ENTITIES:
            raise ValueError(f"Unsupported entity: {entity}")

        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise ValueError(f"Unsupported content type: {content_type}")

        # Generate file path similar to S3
        local_filename = f"uploads/{entity}s/users/{user_id}/{uuid.uuid4()}/{filename}"

        # Ensure the directory exists
        file_path = os.path.join(settings.MEDIA_ROOT, local_filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Generate URLs using Django's media URL
        media_url = settings.MEDIA_URL if hasattr(settings, "MEDIA_URL") else "/media/"
        base_url = getattr(settings, "LOCAL_STORAGE_BASE_URL", "http://localhost:8000")

        # For local development, the presigned URL is just the direct upload endpoint
        # You would handle the actual upload through Django's normal file upload mechanism
        object_url = f"{base_url}{media_url}{local_filename}"

        return PresignedUrl(
            url=object_url,  # In local mode, this would be handled by your frontend differently
            object_key=local_filename,
            object_url=object_url,
        )

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for local storage.
        """
        name = unicodedata.normalize("NFKD", filename)
        name = name.encode("ascii", "ignore").decode("ascii")
        name = quote(name, safe="!-_.*'()")
        return name
