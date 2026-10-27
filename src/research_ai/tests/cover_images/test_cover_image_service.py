import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from research_ai.models import CoverImageGeneration, LLMUsageEvent
from research_ai.services.cover_image_service import (
    CoverImageGenerationEnqueueError,
    CoverImageGenerationUnavailableError,
    CoverImageService,
)
from research_ai.services.openrouter_image_client import GeneratedImage
from research_ai.services.usage_budget import UsageLimitExceededError, budget_status
from research_ai.services.usage_budget.config import COVER_IMAGE_FEATURE


def _png(width: int = 42, height: int = 18) -> bytes:
    output = io.BytesIO()
    Image.new("RGBA", (width, height), (10, 20, 30, 255)).save(output, format="PNG")
    return output.getvalue()


def _generated(*, cost_microusd=40_000) -> GeneratedImage:
    return GeneratedImage(
        data=_png(), cost_microusd=cost_microusd, input_tokens=100, output_tokens=4000
    )


class CoverImageServiceTests(TestCase):
    def setUp(self):
        # The tier's shared spend is cached across tests.
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="cover@researchhub_test.com",
            password="password",
            email="cover@researchhub_test.com",
        )
        self.client = Mock()
        self.client.generate.return_value = _generated()
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

    def test_run_forbids_drawing_a_logo(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)

        # Assert
        call = self.client.generate.call_args_list[0].kwargs
        self.assertIn("Never draw a logo", call["prompt"])

    def test_run_generates_and_stores_one_banner(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.COMPLETED)
        self.client.generate.assert_called_once()
        key = generation.image_key
        self.assertTrue(key.startswith(f"uploads/posts/users/{self.user.id}/"))
        self.assertTrue(key.endswith("/cover.jpg"))
        stored = self.storage.save.call_args_list[0].args[1]
        with Image.open(stored) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size, (42, 18))

    def test_run_fails_when_no_banner_was_generated(self):
        # Arrange
        generation = self._generation()
        self.client.generate.side_effect = RuntimeError("unavailable")

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.FAILED)
        self.assertEqual(generation.image_key, "")
        self.storage.save.assert_not_called()

    def test_run_skips_a_request_already_claimed(self):
        # Arrange
        generation = self._generation(status=CoverImageGeneration.Status.PROCESSING)

        # Act
        self.service.run(generation.id)

        # Assert
        self.client.generate.assert_not_called()

    def test_run_charges_the_users_budget_what_openrouter_billed(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)

        # Assert
        event = LLMUsageEvent.objects.get(user=self.user)
        self.assertEqual(event.feature, COVER_IMAGE_FEATURE)
        self.assertEqual(event.provider, "openrouter")
        self.assertEqual(event.model, CoverImageService.MODEL)
        self.assertEqual(event.cost_microusd, 40_000)
        self.assertEqual(event.output_tokens, 4000)

    def test_run_charges_an_image_it_cannot_store(self):
        # Arrange
        generation = self._generation()
        self.client.generate.return_value = GeneratedImage(
            data=b"not an image", cost_microusd=40_000
        )

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.FAILED)
        self.assertEqual(LLMUsageEvent.objects.get().cost_microusd, 40_000)

    def test_run_charges_nothing_when_no_image_came_back(self):
        # Arrange
        generation = self._generation()
        self.client.generate.side_effect = RuntimeError("unavailable")

        # Act
        self.service.run(generation.id)

        # Assert
        self.assertFalse(LLMUsageEvent.objects.exists())

    def test_generating_spends_dollars_but_takes_no_turns(self):
        # Arrange
        generation = self._generation()

        # Act
        self.service.run(generation.id)
        status = budget_status(self.user)

        # Assert
        self.assertEqual(status.spent_today_microusd, 40_000)
        self.assertEqual(status.turns_used, 0)

    def test_start_is_refused_once_the_daily_budget_is_spent(self):
        # Arrange
        LLMUsageEvent.objects.create(
            user=self.user,
            feature="notebook_chat",
            tier="default",
            provider="openrouter",
            model="m",
            cost_microusd=budget_status(self.user).daily_budget_microusd,
        )

        # Act / Assert
        with self.assertRaises(UsageLimitExceededError):
            self.service.start(user=self.user, document_type="GRANT", title="A study")
        self.assertFalse(CoverImageGeneration.objects.exists())

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

    def test_public_gives_the_image_url(self):
        # Arrange
        generation = self._generation(
            status=CoverImageGeneration.Status.COMPLETED,
            image_key="uploads/a/cover.jpg",
        )

        # Act
        data = self.service.public(generation)

        # Assert
        self.assertEqual(
            data["image"],
            {
                "key": "uploads/a/cover.jpg",
                "url": "https://cdn.test/uploads/a/cover.jpg",
            },
        )
        self.assertIsNone(data["error"])
