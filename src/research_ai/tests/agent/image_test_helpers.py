"""Real image bytes for tests: an image is only sent once it has been read."""

import io

from PIL import Image

from research_ai.services.agent.images import MANY_IMAGES_SIDE_PX


def image_bytes(image_format: str, size: tuple[int, int] = (1, 1)) -> bytes:
    """A blank ``size`` image encoded as ``image_format`` (a Pillow format name)."""
    buffer = io.BytesIO()
    Image.new("L", size).save(buffer, image_format)
    return buffer.getvalue()


JPEG = image_bytes("JPEG")
PNG = image_bytes("PNG")
# Sent on its own, but too large for a request with more than 20 images.
WIDE_PNG = image_bytes("PNG", (MANY_IMAGES_SIDE_PX + 1, 1))
