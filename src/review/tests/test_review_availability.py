from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from review.services.review_service import REVIEW_COOLDOWN_DAYS, get_review_availability
from user.tests.helpers import create_random_default_user


class TestReviewAvailability(APITestCase):
    def setUp(self):
        self.user = create_random_default_user("reviewer")
        self.paper = create_paper(uploaded_by=self.user)

    def _create_review(self, user=None, days_ago=0):
        user = user or self.user
        thread = RhCommentThreadModel.objects.create(
            content_object=self.paper, created_by=user, updated_by=user
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=user,
            updated_by=user,
            comment_type=COMMUNITY_REVIEW,
        )
        if days_ago:
            RhCommentModel.objects.filter(id=comment.id).update(
                created_date=timezone.now() - timedelta(days=days_ago)
            )
        return comment

    # --- Service tests ---

    def test_can_review_when_no_previous_reviews(self):
        # Arrange: no reviews exist

        # Act
        result = get_review_availability(self.user)

        # Assert
        self.assertTrue(result.can_review)
        self.assertIsNone(result.available_at)

    def test_cannot_review_within_cooldown_period(self):
        # Arrange
        self._create_review(days_ago=REVIEW_COOLDOWN_DAYS - 1)

        # Act
        result = get_review_availability(self.user)

        # Assert
        self.assertFalse(result.can_review)
        self.assertIsNotNone(result.available_at)

    def test_can_review_after_cooldown_expires(self):
        # Arrange
        self._create_review(days_ago=REVIEW_COOLDOWN_DAYS + 1)

        # Act
        result = get_review_availability(self.user)

        # Assert
        self.assertTrue(result.can_review)
        self.assertIsNone(result.available_at)

    # --- API tests ---

    def test_review_availability_endpoint(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get("/api/review/availability/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["can_review"])

    def test_create_review_blocked_during_cooldown(self):
        # Arrange
        self._create_review()
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            f"/api/paper/{self.paper.id}/comments/create_rh_comment/",
            {"comment_content_json": {"ops": [{"insert": "test"}]}, "comment_type": "REVIEW"},
        )

        # Assert
        self.assertEqual(response.status_code, 403)

