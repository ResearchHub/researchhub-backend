import os

from storages.backends.s3boto3 import S3Boto3Storage

INLINE_CONTENT_TYPES = {
    ".csv": "text/csv",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".txt": "text/plain",
    ".webp": "image/webp",
}

DOWNLOAD_CONTENT_TYPE = "application/octet-stream"


class SafeS3Storage(S3Boto3Storage):
    def get_object_parameters(self, name):
        params = super().get_object_parameters(name)

        extension = os.path.splitext(name)[1].lower()
        content_type = INLINE_CONTENT_TYPES.get(extension)
        if content_type is None:
            params["ContentType"] = DOWNLOAD_CONTENT_TYPE
            params["ContentDisposition"] = "attachment"
        else:
            params["ContentType"] = content_type

        return params
