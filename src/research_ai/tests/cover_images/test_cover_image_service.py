import base64
import io
from datetime import timedelta
from decimal import Decimal
from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from note.tests.helpers import create_note
from research_ai.models import CoverImageGeneration, LLMUsageEvent, NoteCoverLogo
from research_ai.prompts.cover_image_prompts import CoverImagePrompts
from research_ai.services.agent_persistence import AgentConversationService
from research_ai.services.cover_image_service import (
    CoverImageGenerationEnqueueError,
    CoverImageGenerationUnavailableError,
    CoverImageNoteError,
    CoverImageService,
)
from research_ai.services.openrouter_image_client import GeneratedImage
from research_ai.services.usage_budget import UsageLimitExceededError, budget_status
from research_ai.services.usage_budget.config import COVER_IMAGE_FEATURE
from research_ai.tests.agent_files.helpers import make_file
from researchhub_access_group.constants import ADMIN
from researchhub_access_group.models import Permission
from researchhub_document.models import ResearchhubUnifiedDocument


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
        self.private_storage = Mock()
        self.service = CoverImageService(
            client=self.client,
            storage=self.storage,
            enqueue=self.enqueue,
            private_storage=self.private_storage,
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

    def _note(self, *, access=True):
        note, _ = create_note(self.user, organization=None)
        if access:
            Permission.objects.create(
                access_type=ADMIN,
                content_type=ContentType.objects.get_for_model(
                    ResearchhubUnifiedDocument
                ),
                object_id=note.unified_document_id,
                user=self.user,
            )
        return note

    def _chat_logo(self, note):
        conversations = AgentConversationService()
        conversation = conversations.create(user=self.user, workflow="notebook_chat")
        message = conversations.add_human_message(conversation, "Here is our logo")
        logo = make_file(
            self.user,
            message=message,
            filename="logo.png",
            content_type="image/png",
            text="",
            etag='"logo-etag"',
        )
        NoteCoverLogo.objects.create(note=note, file=logo, set_by=self.user)
        return logo

    def test_start_refuses_a_note_the_user_cannot_open(self):
        # Arrange
        note = self._note(access=False)

        # Act / Assert
        with self.assertRaises(CoverImageNoteError):
            self.service.start(
                user=self.user, document_type="GRANT", title="A study", note_id=note.id
            )
        self.assertFalse(CoverImageGeneration.objects.exists())

    def test_start_takes_the_logo_the_notes_chat_recorded(self):
        # Arrange
        note = self._note()
        logo = self._chat_logo(note)

        # Act
        generation = self.service.start(
            user=self.user, document_type="GRANT", title="A study", note_id=note.id
        )

        # Assert
        self.assertEqual(generation.note, note)
        self.assertEqual(generation.logo_file, logo)

    def test_start_for_a_note_without_a_cover_logo_uses_none(self):
        # Arrange
        note = self._note()

        # Act
        generation = self.service.start(
            user=self.user, document_type="GRANT", title="A study", note_id=note.id
        )

        # Assert
        self.assertIsNone(generation.logo_file)

    def test_run_places_the_logo_from_a_scaled_down_reference(self):
        # Arrange
        logo = self._chat_logo(self._note())
        generation = self._generation(logo_file=logo)
        self.private_storage.read.return_value = _png(2048, 512)

        # Act
        self.service.run(generation.id)

        # Assert
        generation.refresh_from_db()
        self.assertEqual(generation.status, CoverImageGeneration.Status.COMPLETED)
        self.private_storage.read.assert_called_once_with(
            logo.storage_key,
            max_bytes=CoverImageService.LOGO_MAX_BYTES,
            if_match='"logo-etag"',
        )
        call = self.client.generate.call_args_list[0].kwargs
        self.assertIn("the provided logo", call["prompt"])
        (reference,) = call["reference_images"]
        prefix = "data:image/png;base64,"
        self.assertTrue(reference.startswith(prefix))
        with Image.open(
            io.BytesIO(base64.b64decode(reference[len(prefix) :]))
        ) as image:
            self.assertEqual(image.size, (1024, 256))

    def test_run_fails_when_the_logo_cannot_be_read(self):
        # Arrange
        generation = self._generation(logo_file=self._chat_logo(self._note()))
        self.private_storage.read.side_effect = ValueError("object exceeds limit")

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
            _generated(cost_microusd=40_000),
            RuntimeError("moderation_blocked"),
            _generated(cost_microusd=45_000),
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
        self.assertEqual(event.cost_microusd, 40_000 * CoverImagePrompts.VARIANT_COUNT)
        self.assertEqual(event.output_tokens, 4000 * CoverImagePrompts.VARIANT_COUNT)

    def test_run_charges_only_the_images_that_came_back(self):
        # Arrange
        generation = self._generation()
        self.client.generate.side_effect = [
            _generated(cost_microusd=40_000),
            RuntimeError("upstream failed, not billed"),
            _generated(cost_microusd=45_000),
        ]

        # Act
        self.service.run(generation.id)

        # Assert
        self.assertEqual(LLMUsageEvent.objects.get().cost_microusd, 85_000)

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
        self.assertEqual(
            status.spent_today_microusd, 40_000 * CoverImagePrompts.VARIANT_COUNT
        )
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
