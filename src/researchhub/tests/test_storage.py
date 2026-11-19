from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings

from paper.models import Figure
from researchhub.storage import SafeS3Storage
from user.models import Author


@override_settings(AWS_STORAGE_BUCKET_NAME="test-bucket")
class SafeS3StorageTests(SimpleTestCase):
    def setUp(self):
        self.storage = SafeS3Storage()

    def _write_parameters(self, name, content):
        # Builds what would be sent to S3 for the object without sending it.
        return self.storage._get_write_parameters(name, content)

    def test_ignores_content_type_declared_by_the_uploader(self):
        # Arrange
        upload = SimpleUploadedFile(
            "cover.png", b"<script>alert(1)</script>", content_type="text/html"
        )

        # Act
        params = self._write_parameters("organizations/cover_image/cover.png", upload)

        # Assert
        self.assertEqual(params["ContentType"], "image/png")
        self.assertNotIn("ContentDisposition", params)

    def test_stores_displayable_extensions_with_their_content_type(self):
        cases = {
            "report.csv": "text/csv",
            "figure.gif": "image/gif",
            "photo.jpeg": "image/jpeg",
            "photo.JPG": "image/jpeg",
            "paper.pdf": "application/pdf",
            "figure.png": "image/png",
            "RH-POST-DISCUSSION-USER-1.txt": "text/plain",
            "thumbnail.webp": "image/webp",
        }
        for name, content_type in cases.items():
            with self.subTest(name=name):
                # Act
                params = self._write_parameters(f"uploads/{name}", ContentFile(b"x"))

                # Assert
                self.assertEqual(params["ContentType"], content_type)
                self.assertNotIn("ContentDisposition", params)

    def test_stores_every_other_name_as_a_download(self):
        names = [
            "page.html",
            "page.HTM",
            "page.xhtml",
            "image.svg",
            "feed.xml",
            "script.js",
            "page.html.gz",
            "no_extension",
            "archive.png.html",
        ]
        for name in names:
            with self.subTest(name=name):
                # Arrange
                upload = SimpleUploadedFile(name, b"<svg/>", content_type="text/html")

                # Act
                params = self._write_parameters(f"uploads/{name}", upload)

                # Assert
                self.assertEqual(params["ContentType"], "application/octet-stream")
                self.assertEqual(params["ContentDisposition"], "attachment")
                self.assertNotIn("ContentEncoding", params)

    def test_model_file_storages_do_not_serve_markup(self):
        fields = {
            "author profile image": Author._meta.get_field("profile_image"),
            "figure file": Figure._meta.get_field("file"),
            "figure thumbnail": Figure._meta.get_field("thumbnail"),
        }
        for label, field in fields.items():
            with self.subTest(label):
                # Arrange
                upload = SimpleUploadedFile(
                    "page.html", b"<html></html>", content_type="text/html"
                )

                # Act
                params = field.storage._get_write_parameters("page.html", upload)

                # Assert
                self.assertEqual(params["ContentType"], "application/octet-stream")
                self.assertEqual(params["ContentDisposition"], "attachment")
