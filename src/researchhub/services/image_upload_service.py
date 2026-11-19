import uuid
from typing import NamedTuple

from django.core.files.uploadedfile import UploadedFile
from PIL import Image


class ImageFormat(NamedTuple):
    extension: str
    content_type: str


IMAGE_FORMATS = {
    "GIF": ImageFormat("gif", "image/gif"),
    "JPEG": ImageFormat("jpg", "image/jpeg"),
    "PNG": ImageFormat("png", "image/png"),
    "WEBP": ImageFormat("webp", "image/webp"),
}

_FORMAT_ALIASES = {"MPO": "JPEG"}

MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024

INVALID_IMAGE_MESSAGE = "Upload a valid JPEG, PNG, GIF or WebP image."


class InvalidImageUploadError(ValueError):
    pass


def normalize_image_upload(
    upload: UploadedFile, *, max_bytes: int = MAX_IMAGE_UPLOAD_BYTES
) -> UploadedFile:
    if upload.size is not None and upload.size > max_bytes:
        raise InvalidImageUploadError(
            f"Upload an image no larger than {max_bytes // (1024 * 1024)} MB."
        )

    try:
        with Image.open(upload, formats=tuple(IMAGE_FORMATS)) as image:
            image.verify()
            image_format = _FORMAT_ALIASES.get(image.format, image.format)
            extension, content_type = IMAGE_FORMATS[image_format]
    except Exception as e:
        raise InvalidImageUploadError(INVALID_IMAGE_MESSAGE) from e

    upload.seek(0)
    upload.name = f"{uuid.uuid4().hex}.{extension}"
    upload.content_type = content_type
    return upload
