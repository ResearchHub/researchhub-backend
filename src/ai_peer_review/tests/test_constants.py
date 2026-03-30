from django.test import TestCase

from ai_peer_review.constants import OverallRating, ReviewStatus


class AIPeerReviewConstantsTests(TestCase):
    def test_review_status_choices(self):
        self.assertEqual(ReviewStatus.PENDING, "pending")
        self.assertEqual(ReviewStatus.COMPLETED, "completed")

    def test_overall_rating_choices(self):
        self.assertEqual(OverallRating.EXCELLENT, "excellent")
        self.assertEqual(OverallRating.POOR, "poor")
