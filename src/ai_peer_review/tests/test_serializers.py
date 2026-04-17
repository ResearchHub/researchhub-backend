from unittest.mock import MagicMock

from django.test import SimpleTestCase

from ai_peer_review.models import ReviewStatus
from ai_peer_review.serializers import build_proposal_comparison_row


class BuildProposalComparisonRowTests(SimpleTestCase):
    def test_no_review_returns_empty_scores(self):
        row = build_proposal_comparison_row(None, 42, "My title", None)
        self.assertEqual(row["unified_document_id"], 42)
        self.assertEqual(row["proposal_title"], "My title")
        self.assertIsNone(row["review_id"])
        self.assertIsNone(row["fundability"])

    def test_non_completed_review_has_no_dimension_scores(self):
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
        self.assertIsNone(row["fundability"])
        self.assertEqual(row["editorial_feedback"]["expert_insights"], "x")
