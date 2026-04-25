from unittest.mock import MagicMock

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from ai_peer_review.constants import CATEGORY_KEYS
from ai_peer_review.models import ReviewStatus
from ai_peer_review.serializers import (
    EditorialFeedbackUpsertSerializer,
    build_proposal_comparison_row,
)


class BuildProposalComparisonRowTests(SimpleTestCase):
    def test_no_review_returns_empty_scores(self):
        row = build_proposal_comparison_row(None, 42, "My title", None)
        self.assertEqual(row["unified_document_id"], 42)
        self.assertEqual(row["proposal_title"], "My title")
        self.assertIsNone(row["review_id"])
        self.assertIsNone(row["categories"])

    def test_non_completed_review_has_no_category_scores(self):
        review = MagicMock()
        review.id = 5
        review.status = ReviewStatus.PENDING
        review.overall_rating = None
        review.overall_score_numeric = None
        review.result_data = {}
        row = build_proposal_comparison_row(
            review, 1, "T", {"id": 1, "expert_insights": "x"}
        )
        self.assertEqual(row["review_id"], 5)
        self.assertIsNone(row["categories"])
        self.assertEqual(row["editorial_feedback"]["expert_insights"], "x")

    def test_completed_review_exposes_category_map(self):
        review = MagicMock()
        review.id = 1
        review.status = ReviewStatus.COMPLETED
        review.overall_rating = "good"
        review.overall_score_numeric = 4
        review.result_data = {
            "categories": {
                "overall_impact": {"score": "Medium"},
            }
        }
        row = build_proposal_comparison_row(review, 9, "Title", None)
        self.assertEqual(row["categories"]["overall_impact"], "Medium")
        for key in CATEGORY_KEYS:
            if key != "overall_impact":
                self.assertIsNone(row["categories"][key])


class EditorialFeedbackUpsertSerializerTests(SimpleTestCase):
    def test_create_requires_all_categories(self):
        ser = EditorialFeedbackUpsertSerializer(
            data={"expert_insights": "hi", "categories": []},
            context={"is_create": True},
        )
        with self.assertRaises(ValidationError):
            ser.is_valid(raise_exception=True)

    def test_create_accepts_full_category_set(self):
        cats = [{"category_code": k, "score": "high"} for k in CATEGORY_KEYS]
        ser = EditorialFeedbackUpsertSerializer(
            data={"expert_insights": "hi", "categories": cats},
            context={"is_create": True},
        )
        self.assertTrue(ser.is_valid(), ser.errors)
