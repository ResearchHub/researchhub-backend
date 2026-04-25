from django.test import TestCase

from ai_peer_review.models import ProposalReview, ReviewStatus
from ai_peer_review.services.proposal_review_comment_service import (
    AI_EXPERT_EMAIL,
    AI_REVIEW_COMMENT_TYPE,
    proposal_review_to_plain_text,
    proposal_review_to_tiptap_content,
    upsert_proposal_review_comment,
)
from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from review.models import Review
from user.models import User
from user.tests.helpers import create_random_authenticated_user


class ProposalReviewCommentServiceTests(TestCase):
    def setUp(self):
        self.reviewer = create_random_authenticated_user("ai_review_editor")
        self.proposal_owner = create_random_authenticated_user("ai_review_owner")
        User.objects.create(
            email=AI_EXPERT_EMAIL,
            first_name="AI",
            last_name="Expert",
            is_official_account=True,
        )
        self.proposal_post = create_post(
            created_by=self.proposal_owner,
            document_type=PREREGISTRATION,
            title="Proposal for AI review comments",
        )
        self.review = ProposalReview.objects.create(
            created_by=self.reviewer,
            unified_document=self.proposal_post.unified_document,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_confidence="High",
            overall_score_numeric=2,
            overall_rationale="Strong fit with moderate execution risk.",
            result_data={
                "major_strengths": ["Important problem", "Reasonable methods"],
                "major_weaknesses": ["Sample size justification is limited"],
                "fatal_flaws": [],
                "categories": {
                    "overall_impact": {"score": "High"},
                    "importance_significance_innovation": {"score": "Medium"},
                    "rigor_and_feasibility": {"score": "Medium"},
                    "additional_review_criteria": {"score": "High"},
                },
            },
        )

    def test_proposal_review_to_tiptap_content_creates_structured_doc(self):
        payload = proposal_review_to_tiptap_content(self.review)
        self.assertEqual(payload["type"], "doc")
        self.assertEqual(payload["content"][0]["type"], "paragraph")
        title_text = payload["content"][0]["content"][0]["text"]
        self.assertEqual(title_text, "AI Proposal Review")
        self.assertEqual(payload["content"][3]["type"], "blockquote")
        self.assertEqual(payload["content"][5]["type"], "bulletList")
        self.assertEqual(payload["content"][7]["type"], "orderedList")

    def test_upsert_proposal_review_comment_creates_thread_and_comment(self):
        comment = upsert_proposal_review_comment(self.review)

        self.assertIsNotNone(comment)
        self.assertEqual(comment.comment_content_type, TIPTAP)
        self.assertEqual(comment.comment_type, AI_REVIEW_COMMENT_TYPE)
        self.assertEqual(comment.thread.thread_type, AI_REVIEW_COMMENT_TYPE)
        self.assertEqual(comment.thread.object_id, self.proposal_post.id)

        ai_user = User.objects.get(email=AI_EXPERT_EMAIL)
        self.assertEqual(comment.created_by_id, ai_user.id)
        self.assertIn("Overall rating: good", comment.plain_text)
        self.assertTrue(
            RhCommentThreadModel.objects.filter(
                id=comment.thread_id,
                thread_reference=(
                    f"ai_proposal_review:{self.review.unified_document_id}:standalone"
                ),
            ).exists()
        )
        review_row = Review.objects.get(object_id=comment.id)
        self.assertEqual(review_row.score, 2.0)

    def test_upsert_proposal_review_comment_updates_existing_comment(self):
        original = upsert_proposal_review_comment(self.review)

        self.review.overall_rating = "excellent"
        self.review.overall_score_numeric = 5
        self.review.overall_rationale = "Very strong overall package."
        self.review.save(
            update_fields=[
                "overall_rating",
                "overall_score_numeric",
                "overall_rationale",
                "updated_date",
            ]
        )

        updated = upsert_proposal_review_comment(self.review)
        self.assertEqual(original.id, updated.id)
        top_level_count = RhCommentModel.objects.filter(
            thread=updated.thread,
            parent__isnull=True,
        ).count()
        self.assertEqual(
            top_level_count,
            1,
        )
        self.assertIn("Overall rating: excellent", updated.plain_text)
        self.assertIn("Overall score: 5/5", updated.plain_text)
        review_row = Review.objects.get(object_id=updated.id)
        self.assertEqual(review_row.score, 5.0)

    def test_proposal_review_to_plain_text_contains_core_sections(self):
        text = proposal_review_to_plain_text(self.review)
        self.assertIn("AI Proposal Review", text)
        self.assertIn("Category scores:", text)
        self.assertIn("Major strengths:", text)
        self.assertIn("Major weaknesses:", text)
        self.assertIn("Fatal flaws:", text)
