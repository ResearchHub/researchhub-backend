"""Loading the images an ``ImageBlock`` refers to when a request is built."""

import io
import logging
from collections.abc import Callable, Iterable

from PIL import Image

from research_ai.services.agent.types import ImageBlock, Message, ToolResultBlock

logger = logging.getLogger(__name__)

# The types every provider accepts, with the Pillow format that reads each.
_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/gif": "GIF",
    "image/webp": "WEBP",
}
IMAGE_MEDIA_TYPES = frozenset(_FORMATS)
# Bedrock and Claude reject an image over 8000 px on either side, and over
# 2000 px once a request carries more than 20 images.
MAX_IMAGE_SIDE_PX = 8000
MANY_IMAGES_SIDE_PX = 2000
MANY_IMAGES = 20

# ``ref`` -> the image's bytes; raises ``ImageUnavailableError`` when it is gone.
ImageLoader = Callable[[str], bytes]


class ImageUnavailableError(LookupError):
    """The referenced image no longer exists; the model gets a placeholder."""


def max_image_side_px(messages: Iterable[Message]) -> int:
    """The longest side an image may have in a request that sends ``messages``."""
    images = 0
    for message in messages:
        for block in message.content:
            if isinstance(block, ImageBlock):
                images += 1
            elif isinstance(block, ToolResultBlock):
                images += len(block.images)
    return MANY_IMAGES_SIDE_PX if images > MANY_IMAGES else MAX_IMAGE_SIDE_PX


def load_image(
    block: ImageBlock,
    *,
    loader: ImageLoader | None,
    vision: bool,
    max_bytes: int,
    max_side_px: int = MAX_IMAGE_SIDE_PX,
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
    problem = _problem(data, block.media_type, max_side_px)
    if problem:
        logger.warning("image %r %s", block.ref, problem)
        return None
    return data


def _problem(data: bytes, media_type: str, max_side_px: int) -> str | None:
    """Why a provider would reject ``data``; ``None`` when it would not."""
    try:
        with Image.open(io.BytesIO(data), formats=[_FORMATS[media_type]]) as image:
            width, height = image.size
            if max(width, height) > max_side_px:
                return f"is {width}x{height} px, over the limit"
    except Exception:  # noqa: BLE001 - whatever Pillow raises, it cannot be sent
        return f"cannot be read as {media_type}"
    return None


def image_placeholder(block: ImageBlock) -> str:
    """The text a model sees in place of an image it is not sent."""
    return f"[Image not shown: {block.label}]" if block.label else "[Image not shown]"
