"""Real image bytes for tests: an image is only sent once its header is read."""

import io

from PIL import Image


def image_bytes(image_format: str, size: tuple[int, int] = (1, 1)) -> bytes:
    """A blank ``size`` image encoded as ``image_format`` (a Pillow format name)."""
    buffer = io.BytesIO()
    Image.new("L", size).save(buffer, image_format)
    return buffer.getvalue()


JPEG = image_bytes("JPEG")
PNG = image_bytes("PNG")
