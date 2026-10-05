"""Loading the images an ``ImageBlock`` refers to when a request is built."""

import io
import logging
from collections.abc import Callable

from PIL import Image

from research_ai.services.agent.types import ImageBlock

logger = logging.getLogger(__name__)

# The types every provider accepts, with the Pillow format that reads each.
_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}
IMAGE_MEDIA_TYPES = frozenset(_FORMATS)
# Bedrock and Claude reject an image over 8000 px on either side.
MAX_IMAGE_SIDE_PX = 8000

# ``ref`` -> the image's bytes; raises ``ImageUnavailableError`` when it is gone.
ImageLoader = Callable[[str], bytes]


class ImageUnavailableError(LookupError):
    """The referenced image no longer exists; the model gets a placeholder."""


def load_image(
    block: ImageBlock, *, loader: ImageLoader | None, vision: bool, max_bytes: int
) -> bytes | None:
    """The bytes to send for ``block``, or ``None`` to send its placeholder.

    Any other loader failure propagates: a placeholder sent for a transient
    error would change the conversation the model sees between turns.
    """
    if not vision:
        return None
    if loader is None:
        logger.warning("no image loader is configured; image %r not sent", block.ref)
        return None
    if block.media_type not in IMAGE_MEDIA_TYPES:
        logger.warning("image %r has unsupported type %r", block.ref, block.media_type)
        return None
    try:
        data = loader(block.ref)
    except ImageUnavailableError:
        logger.warning("image %r is no longer available", block.ref)
        return None
    if len(data) > max_bytes:
        logger.warning("image %r is %d bytes, over the limit", block.ref, len(data))
        return None
    # A mislabelled or oversized image is a 400 on every later turn.
    size = _dimensions(data, block.media_type)
    if size is None:
        logger.warning("image %r cannot be read as %s", block.ref, block.media_type)
        return None
    if max(size) > MAX_IMAGE_SIDE_PX:
        logger.warning("image %r is %dx%d px, over the limit", block.ref, *size)
        return None
    return data


def _dimensions(data: bytes, media_type: str) -> tuple[int, int] | None:
    """Width and height from the header; ``None`` when it is not that type."""
    try:
        with Image.open(io.BytesIO(data), formats=[_FORMATS[media_type]]) as image:
            return image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def image_placeholder(block: ImageBlock) -> str:
    """The text a model sees in place of an image it is not sent."""
    return f"[Image not shown: {block.label}]" if block.label else "[Image not shown]"
