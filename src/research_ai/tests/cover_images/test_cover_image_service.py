import base64
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from research_ai.models import CoverImageGeneration
from research_ai.prompts.cover_image_prompts import CoverImagePrompts
from research_ai.services.cover_image_service import (
    CoverImageGenerationEnqueueError,
    CoverImageGenerationUnavailableError,
    CoverImageLogoError,
    CoverImageService,
)


def _png(width: int = 42, height: int = 18) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 20, 30, 255)).save(output, format="PNG")
    return output.getvalue()


class CoverImageServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="cover@researchhub_test.com",
            password="password",
            email="cover@researchhub_test.com",
        )
        self.client = Mock()
        self.client.generate.return_value = _png()
        self.storage = Mock()
        self.storage.save.side_effect = lambda key, content: key
        self.storage.url.side_effect = lambda key: f"https://cdn.test/{key}"
        self.enqueue = Mock()
        self.service = CoverImageService(
            client=self.client, storage=self.storage, enqueue=self.enqueue
        )

    def _generation(self, **overrides):
        fields = {
            "created_by": self.user,
            "document_type": CoverImageGeneration.DocumentType.GRANT,
            "title": "Epothilone B and anesthetic sensitivity",
            "organization": "Athanatos Foundation",
            "funding_amount_usd": Decimal(23000),
        }
        return CoverImageGeneration.objects.create(**{**fields, **overrides})

    def test_start_records_and_queues_the_request(self):
        # Act
        generation = self.service.start(
            user=self.user,
            document_type="GRANT",
            title="A study",
            funding_amount_usd=Decimal(1000),
        )

        # Assert
        self.assertEqual(generation.status, CoverImageGeneration.Status.PENDING)
        self.assertEqual(generation.created_by, self.user)
        self.enqueue.assert_called_once_with(generation.id)

    @override_settings(OPENROUTER_API_KEY="")
    def test_start_without_an_api_key_is_refused(self):
        # Arrange
        service = CoverImageService(storage=self.storage, enqueue=self.enqueue)

        # Act / Assert
        with self.assertRaises(CoverImageGenerationUnavailableError):
            service.start(user=self.user, document_type="GRANT", title="A study")
        self.assertFalse(CoverImageGeneration.objects.exists())

    def test_start_marks_the_request_failed_when_it_cannot_be_queued(self):
        # Arrange
        self.enqueue.side_effect = ConnectionError("broker down")

        # Act
        with self.assertRaises(CoverImageGenerationEnqueueError):
            self.service.start(user=self.user, document_type="GRANT", title="A study")

        # Assert
        generation = CoverImageGeneration.objects.get()
        self.assertEqual(generation.status, CoverImageGeneration.Status.FAILED)

    def test_start_refuses_a_logo_the_user_did_not_upload(self):
        # Act / Assert
        with self.assertRaises(CoverImageLogoError):
            self.service.start(
                user=self.user,
                document_type="GRANT",
                title="A study",
                logo_key="uploads/posts/users/999999/abc/logo.png",
            )
        self.assertFalse(CoverImageGeneration.objects.exists())

    def test_start_keeps_the_users_logo(self):
        # Arrange
        logo_key = f"uploads/posts/users/{self.user.id}/abc/logo.png"

        # Act
        generation = self.service.start(
            user=self.user, document_type="GRANT", title="A study", logo_key=logo_key
        )

        # Assert
        self.assertEqual(generation.logo_key, logo_key)

    def test_run_places_the_logo_from_a_scaled_down_reference(self):
        # Arrange
        generation = self._generation(
            logo_key=f"uploads/posts/users/{self.user.id}/abc/logo.png"
        )
        self.storage.open.return_value = io.BytesIO(_png(2048, 512))

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.COMPLETED)
        call = self.client.generate.call_args_list[0].kwargs
        self.assertIn("the provided logo", call["prompt"])
        (reference,) = call["reference_images"]
        prefix = "data:image/png;base64,"
        self.assertTrue(reference.startswith(prefix))
        with Image.open(io.BytesIO(base64.b64decode(reference[len(prefix) :]))) as logo:
            self.assertEqual(logo.size, (1024, 256))

    def test_run_fails_when_the_logo_cannot_be_read(self):
        # Arrange
        generation = self._generation(
            logo_key=f"uploads/posts/users/{self.user.id}/abc/logo.png"
        )
        self.storage.open.side_effect = FileNotFoundError("gone")

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.FAILED)
        self.client.generate.assert_not_called()

    def test_run_without_a_logo_sends_no_reference(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)

        # Assert
        call = self.client.generate.call_args_list[0].kwargs
        self.assertIsNone(call["reference_images"])
        self.assertIn("Never draw a logo", call["prompt"])

    def test_run_generates_and_stores_one_banner_per_variant(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.COMPLETED)
        self.assertEqual(len(generation.image_keys), CoverImagePrompts.VARIANT_COUNT)
        self.assertEqual(
            self.client.generate.call_count, CoverImagePrompts.VARIANT_COUNT
        )
        for key in generation.image_keys:
            self.assertTrue(key.startswith(f"uploads/posts/users/{self.user.id}/"))
            self.assertTrue(key.endswith("/cover.jpg"))
        stored = self.storage.save.call_args_list[0].args[1]
        with Image.open(stored) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (42, 18))

    def test_run_keeps_the_banners_that_succeeded(self):
        # Arrange
        generation = self._generation()
        self.client.generate.side_effect = [
            _png(),
            RuntimeError("moderation_blocked"),
            _png(),
        ]

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.COMPLETED)
        self.assertEqual(len(generation.image_keys), 2)

    def test_run_fails_when_no_banner_was_generated(self):
        # Arrange
        generation = self._generation()
        self.client.generate.side_effect = RuntimeError("unavailable")

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.FAILED)
        self.assertEqual(generation.image_keys, [])
        self.storage.save.assert_not_called()

    def test_run_skips_a_request_already_claimed(self):
        # Arrange
        generation = self._generation(status=CoverImageGeneration.Status.PROCESSING)

        # Act
        self.service.run(generation.id)

        # Assert
        self.client.generate.assert_not_called()

    def test_get_for_user_hides_other_users_requests(self):
        # Arrange
        generation = self._generation()
        other = get_user_model().objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )

        # Act
        found = self.service.get_for_user(other, generation.id)

        # Assert
        self.assertIsNone(found)

    def test_get_for_user_fails_a_request_whose_worker_was_lost(self):
        # Arrange
        generation = self._generation()
        CoverImageGeneration.objects.filter(id=generation.id).update(
            created_date=timezone.now()
            - CoverImageService.STALE_AFTER
            - timedelta(minutes=1)
        )

        # Act
        found = self.service.get_for_user(self.user, generation.id)

        # Assert
        self.assertEqual(found.status, CoverImageGeneration.Status.FAILED)

    def test_public_lists_image_urls(self):
        # Arrange
        generation = self._generation(
            status=CoverImageGeneration.Status.COMPLETED,
            image_keys=["uploads/a/cover.jpg"],
        )

        # Act
        data = self.service.public(generation)

        # Assert
        self.assertEqual(
            data["images"],
            [
                {
                    "key": "uploads/a/cover.jpg",
                    "url": "https://cdn.test/uploads/a/cover.jpg",
                }
            ],
        )
        self.assertIsNone(data["error"])
