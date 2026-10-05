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
# Claude takes 100 images a request on its 200K-context models, the fewest.
MAX_REQUEST_IMAGES = 100

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
    # A mislabelled, oversized or damaged image is a 400 on every later turn.
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
            # The header reads fine when the rest is cut short. A PNG's checksums
            # show it; anything else is decoded, a JPEG at an eighth of its size.
            if image.format == "PNG":
                image.verify()
            else:
                image.draft("L", (1, 1))
                image.load()
    except Exception:  # whatever Pillow raises, the image cannot be sent
        return f"cannot be read as {media_type}"
    return None


class RequestImages:
    """Loads one request's images, within what its provider takes in a request.

    Build one per request and ``load`` its images in message order. They are
    admitted first come, first served, so a later image never displaces an
    earlier turn's.
    """

    def __init__(
        self,
        messages: Iterable[Message],
        *,
        loader: ImageLoader | None,
        vision: bool,
        max_image_bytes: int,
        max_request_bytes: int,
        max_message_images: int = MAX_REQUEST_IMAGES,
    ):
        self._loader = loader
        self._vision = vision
        self._max_image_bytes = max_image_bytes
        self._max_side_px = max_image_side_px(messages)
        self._max_message_images = max_message_images
        self._images_left = MAX_REQUEST_IMAGES
        self._bytes_left = max_request_bytes
        self._message_images_left = max_message_images

    def next_message(self) -> None:
        """Start the next message's own allowance of images."""
        self._message_images_left = self._max_message_images

    def load(self, block: ImageBlock) -> bytes | None:
        """The bytes to send for ``block``, or ``None`` to send its placeholder."""
        if min(self._images_left, self._message_images_left, self._bytes_left) <= 0:
            logger.warning("image %r is past what its request may carry", block.ref)
            return None
        data = load_image(
            block,
            loader=self._loader,
            vision=self._vision,
            max_bytes=min(self._max_image_bytes, self._bytes_left),
            max_side_px=self._max_side_px,
        )
        if data is not None:
            self._images_left -= 1
            self._message_images_left -= 1
            self._bytes_left -= len(data)
        return data


def image_placeholder(block: ImageBlock) -> str:
    """The text a model sees in place of an image it is not sent."""
    return f"[Image not shown: {block.label}]" if block.label else "[Image not shown]"
