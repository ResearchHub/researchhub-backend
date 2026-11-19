import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from PIL import Image

from researchhub.services.image_upload_service import (
    InvalidImageUploadError,
    normalize_image_upload,
)

HTML = b"<html><body><script>alert(1)</script></body></html>"


def _image_bytes(image_format: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format=image_format)
    return buffer.getvalue()


class NormalizeImageUploadTests(SimpleTestCase):
    def test_names_and_types_supported_images_by_content(self):
        cases = [
            ("PNG", ".png", "image/png"),
            ("JPEG", ".jpg", "image/jpeg"),
            ("GIF", ".gif", "image/gif"),
            ("WEBP", ".webp", "image/webp"),
        ]
        for image_format, extension, content_type in cases:
            with self.subTest(image_format=image_format):
                # Arrange
                upload = SimpleUploadedFile(
                    "page.html", _image_bytes(image_format), content_type="text/html"
                )

                # Act
                normalized = normalize_image_upload(upload)

                # Assert
                self.assertTrue(normalized.name.endswith(extension))
                self.assertNotIn("page", normalized.name)
                self.assertEqual(normalized.content_type, content_type)
                self.assertEqual(normalized.tell(), 0)

    def test_image_followed_by_markup_is_served_as_an_image(self):
        # Arrange
        upload = SimpleUploadedFile(
            "page.html", _image_bytes("GIF") + HTML, content_type="text/html"
        )

        # Act
        normalized = normalize_image_upload(upload)

        # Assert
        self.assertTrue(normalized.name.endswith(".gif"))
        self.assertEqual(normalized.content_type, "image/gif")

    def test_rejects_content_that_is_not_a_supported_image(self):
        cases = {
            "html named as image": ("avatar.png", HTML, "image/png"),
            "html": ("page.html", HTML, "text/html"),
            "svg": (
                "logo.svg",
                b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
                "image/svg+xml",
            ),
            "image header only": ("avatar.gif", b"GIF89a" + HTML, "image/gif"),
            "unsupported format": ("avatar.bmp", _image_bytes("BMP"), "image/bmp"),
            "empty": ("avatar.png", b"", "image/png"),
        }
        for label, (name, content, content_type) in cases.items():
            with self.subTest(label):
                # Arrange
                upload = SimpleUploadedFile(name, content, content_type=content_type)

                # Act & Assert
                with self.assertRaises(InvalidImageUploadError):
                    normalize_image_upload(upload)

    def test_rejects_image_over_the_size_limit(self):
        # Arrange
        content = _image_bytes("PNG")
        upload = SimpleUploadedFile("avatar.png", content, content_type="image/png")

        # Act & Assert
        with self.assertRaises(InvalidImageUploadError):
            normalize_image_upload(upload, max_bytes=len(content) - 1)

    def test_accepts_image_at_the_size_limit(self):
        # Arrange
        content = _image_bytes("PNG")
        upload = SimpleUploadedFile("avatar.png", content, content_type="image/png")

        # Act
        normalized = normalize_image_upload(upload, max_bytes=len(content))

        # Assert
        self.assertEqual(normalized.content_type, "image/png")
