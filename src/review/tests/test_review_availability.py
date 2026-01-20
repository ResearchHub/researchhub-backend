from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from paper.tests.helpers import create_paper
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from review.services.review_service import (
    MAX_REVIEWS_PER_WINDOW,
    REVIEW_WINDOW_DAYS,
    get_review_availability,
)
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

    def test_can_review_when_under_limit_in_window(self):
        # Arrange: create one review (under limit of 2)
        self._create_review(days_ago=1)

        # Act
        result = get_review_availability(self.user)

        # Assert
        self.assertTrue(result.can_review)
        self.assertIsNone(result.available_at)

    def test_cannot_review_when_at_limit_in_window(self):
        # Arrange: create MAX_REVIEWS_PER_WINDOW reviews in the window
        self._create_review(days_ago=1)
        self._create_review(days_ago=2)

        # Act
        result = get_review_availability(self.user)

        # Assert
        self.assertFalse(result.can_review)
        self.assertIsNotNone(result.available_at)

    def test_can_review_when_oldest_review_exits_window(self):
        # Arrange: create 2 reviews, but oldest is outside the window
        self._create_review(days_ago=REVIEW_WINDOW_DAYS + 1)
        self._create_review(days_ago=1)

        # Act
        result = get_review_availability(self.user)

        # Assert: only 1 review in window, so can review
        self.assertTrue(result.can_review)
        self.assertIsNone(result.available_at)

    def test_available_at_calculated_correctly(self):
        # Arrange: create 2 reviews at specific times
        self._create_review(days_ago=5)  # oldest in window
        self._create_review(days_ago=1)

        # Act
        result = get_review_availability(self.user)

        # Assert: available_at should be when oldest review exits window (5 days ago + 7 = 2 days from now)
        self.assertFalse(result.can_review)
        expected_available = timezone.now() - timedelta(days=5) + timedelta(days=REVIEW_WINDOW_DAYS)
        # Allow 1 minute tolerance for test execution time
        self.assertAlmostEqual(
            result.available_at.timestamp(),
            expected_available.timestamp(),
            delta=60,
        )

    # --- API tests ---

    def test_review_availability_endpoint(self):
        # Arrange
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get("/api/review/availability/")

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["can_review"])

    def test_create_review_blocked_when_at_limit(self):
        # Arrange: create MAX_REVIEWS_PER_WINDOW reviews to hit limit
        for i in range(MAX_REVIEWS_PER_WINDOW):
            self._create_review(days_ago=i)
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.post(
            f"/api/paper/{self.paper.id}/comments/create_rh_comment/",
            {"comment_content_json": {"ops": [{"insert": "test"}]}, "comment_type": "REVIEW"},
        )

        # Assert
        self.assertEqual(response.status_code, 403)

