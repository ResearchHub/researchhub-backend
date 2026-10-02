"""Loading the images an ``ImageBlock`` refers to when a request is built."""

import logging
from collections.abc import Callable

from research_ai.services.agent.types import ImageBlock

logger = logging.getLogger(__name__)

# The types every provider accepts, with the bytes each starts with.
_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
IMAGE_MEDIA_TYPES = frozenset(_SIGNATURES)

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
    # A mislabelled image is a 400 on every later turn of the conversation.
    if not data.startswith(_SIGNATURES[block.media_type]):
        logger.warning("image %r is not %s data", block.ref, block.media_type)
        return None
    return data


def image_placeholder(block: ImageBlock) -> str:
    """The text a model sees in place of an image it is not sent."""
    return f"[Image not shown: {block.label}]" if block.label else "[Image not shown]"
