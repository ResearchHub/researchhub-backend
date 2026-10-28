from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase

from research_ai.models import CoverImageGeneration, LLMUsageEvent


class CoverImageGenerationViewTests(APITestCase):
    COVER_IMAGES_URL = "/api/research_ai/cover-images/"
    ENQUEUE = "research_ai.services.cover_image_service._enqueue_cover_image_generation"

    def setUp(self):
        super().setUp()
        cache.clear()
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username="owner@researchhub_test.com",
            password="password",
            email="owner@researchhub_test.com",
        )
        self.other = user_model.objects.create_user(
            username="other@researchhub_test.com",
            password="password",
            email="other@researchhub_test.com",
        )
        self.client.force_authenticate(self.owner)

    def _payload(self, **overrides):
        return {
            "document_type": "GRANT",
            "title": "Epothilone B and anesthetic sensitivity",
            "subtitle": "Independent replication in rodents & Tetrahymena",
            "organization": "Athanatos Foundation",
            "funding_amount_usd": "23000",
            **overrides,
        }

    def test_requires_authentication(self):
        # Arrange
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            self.COVER_IMAGES_URL, self._payload(), format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    def test_a_blocked_user_is_refused(self):
        # Arrange
        self.owner.probable_spammer = True
        self.owner.save(update_fields=["probable_spammer"])

        # Act
        response = self.client.post(
            self.COVER_IMAGES_URL, self._payload(), format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 403)

    @patch(ENQUEUE)
    def test_post_starts_a_generation(self, enqueue):
        # Act
        response = self.client.post(
            self.COVER_IMAGES_URL, self._payload(), format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "PENDING")
        self.assertIsNone(response.data["image"])
        generation = CoverImageGeneration.objects.get(id=response.data["id"])
        self.assertEqual(generation.created_by, self.owner)
        self.assertEqual(generation.organization, "Athanatos Foundation")
        enqueue.assert_called_once_with(generation.id)

    @patch(ENQUEUE)
    def test_post_rejects_an_unsupported_document_type(self, enqueue):
        # Act
        response = self.client.post(
            self.COVER_IMAGES_URL, self._payload(document_type="PAPER"), format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()

    @patch(ENQUEUE)
    def test_post_once_the_daily_budget_is_spent_is_refused(self, enqueue):
        # Arrange
        LLMUsageEvent.objects.create(
            user=self.owner,
            feature="notebook_chat",
            tier="default",
            provider="openrouter",
            model="m",
            cost_microusd=1_000_000,
        )

        # Act
        response = self.client.post(
            self.COVER_IMAGES_URL, self._payload(), format="json"
        )

        # Assert
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["code"], "usage_limit_exceeded")
        self.assertEqual(response.data["detail"], "Daily AI usage limit reached.")
        enqueue.assert_not_called()

    def test_get_returns_the_generated_image(self):
        # Arrange
        generation = CoverImageGeneration.objects.create(
            created_by=self.owner,
            document_type="GRANT",
            title="A study",
            status=CoverImageGeneration.Status.COMPLETED,
            image_key="uploads/posts/users/1/abc/cover.jpg",
        )

        # Act
        response = self.client.get(f"{self.COVER_IMAGES_URL}{generation.id}/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "COMPLETED")
        self.assertEqual(
            response.data["image"]["key"], "uploads/posts/users/1/abc/cover.jpg"
        )
        self.assertTrue(response.data["image"]["url"])

    def test_get_of_another_users_generation_is_not_found(self):
        # Arrange
        generation = CoverImageGeneration.objects.create(
            created_by=self.other, document_type="GRANT", title="A study"
        )

        # Act
        response = self.client.get(f"{self.COVER_IMAGES_URL}{generation.id}/")

        # Assert
        self.assertEqual(response.status_code, 404)
