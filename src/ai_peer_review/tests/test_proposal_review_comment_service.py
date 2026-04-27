from django.test import TestCase

from ai_peer_review.models import ProposalReview, ReviewStatus
from ai_peer_review.services.proposal_review_comment_service import (
    AI_EXPERT_EMAIL,
    proposal_review_to_tiptap_content,
    upsert_proposal_review_comment,
)
from researchhub_comment.constants.rh_comment_content_types import TIPTAP
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
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
                "overall_summary": "Strong fit with moderate execution risk.",
                "fatal_flaws": [],
                "categories": {
                    "overall_impact": {
                        "score": "High",
                        "items": {
                            "novelty": {
                                "justification": "Clear novelty in framing.",
                            },
                        },
                    },
                    "importance_significance_innovation": {
                        "score": "Medium",
                        "rationale": "Question is important but not novel.",
                        "items": {
                            "question_importance": {
                                "justification": "The core question matters for the field.",
                            },
                        },
                    },
                    "rigor_and_feasibility": {
                        "score": "Medium",
                        "rationale": "Methods are adequate; timeline is tight.",
                        "items": {
                            "methodology": {
                                "justification": "Analytic plan is defensible.",
                            },
                        },
                    },
                    "additional_review_criteria": {
                        "score": "High",
                        "rationale": "Disclosures in order.",
                        "items": {
                            "open_science_adherence": {
                                "justification": "Preregistration and data code noted.",
                            },
                        },
                    },
                },
            },
        )

    def test_proposal_review_to_tiptap_content_creates_structured_doc(self):
        payload = proposal_review_to_tiptap_content(self.review)
        self.assertEqual(payload["type"], "doc")
        self.assertEqual(
            payload["content"][0]["content"][0]["text"],
            "1. Overall Impact. Score: High",
        )
        # Per-category item bullets: overall impact, then 2. Core, 2a/2b/3 each with a bullet list
        self.assertEqual(payload["content"][1]["type"], "bulletList")
        first_item_para = payload["content"][1]["content"][0]["content"][0]
        self.assertEqual(
            [n["text"] for n in first_item_para["content"]],
            ["Novelty", ": ", "Clear novelty in framing."],
        )
        self.assertEqual(
            first_item_para["content"][0]["text"],
            "Novelty",
        )
        self.assertEqual(
            first_item_para["content"][0]["marks"],
            [{"type": "bold"}],
        )
        self.assertEqual(
            first_item_para["content"][2]["marks"],
            [{"type": "italic"}],
        )
        self.assertEqual(
            payload["content"][2]["content"][0]["text"],
            "2. Core Review Factors",
        )
        self.assertEqual(
            payload["content"][3]["content"][0]["text"],
            "2.a Importance, significance, and innovation. Score: Medium",
        )
        self.assertEqual(
            payload["content"][4]["content"][0]["text"],
            "Question is important but not novel.",
        )
        self.assertEqual(payload["content"][5]["type"], "bulletList")
        self.assertEqual(
            payload["content"][6]["content"][0]["text"],
            "2.b Rigor & Feasibility. Score: Medium",
        )
        self.assertEqual(
            payload["content"][7]["content"][0]["text"],
            "Methods are adequate; timeline is tight.",
        )
        self.assertEqual(payload["content"][8]["type"], "bulletList")
        self.assertEqual(
            payload["content"][9]["content"][0]["text"],
            "3. Additional review criteria. Score: High",
        )
        self.assertEqual(
            payload["content"][10]["content"][0]["text"],
            "Disclosures in order.",
        )
        self.assertEqual(payload["content"][11]["type"], "bulletList")
        self.assertEqual(
            payload["content"][12]["content"][0]["text"],
            "Summary",
        )
        self.assertEqual(
            payload["content"][13]["content"][0]["text"],
            "Strong fit with moderate execution risk.",
        )
        self.assertEqual(payload["content"][14], {"type": "paragraph"})
        self.assertNotIn("blockquote", [b.get("type") for b in payload["content"]])
        bullet_idx = [
            i for i, b in enumerate(payload["content"]) if b["type"] == "bulletList"
        ]
        # One bullet list per category; fatal_flaws is empty
        self.assertEqual(len(bullet_idx), 4)

    def test_upsert_proposal_review_comment_creates_thread_and_comment(self):
        comment = upsert_proposal_review_comment(self.review)

        self.assertIsNotNone(comment)
        self.assertEqual(comment.comment_content_type, TIPTAP)
        self.assertEqual(comment.comment_type, COMMUNITY_REVIEW)
        self.assertEqual(comment.thread.thread_type, COMMUNITY_REVIEW)
        self.assertEqual(comment.thread.object_id, self.proposal_post.id)

        ai_user = User.objects.get(email=AI_EXPERT_EMAIL)
        self.assertEqual(comment.created_by_id, ai_user.id)
        self.assertIn("Overall Impact", comment.plain_text)
        self.assertIn("Strong fit with moderate execution risk.", comment.plain_text)
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
        result_data = dict(self.review.result_data or {})
        result_data["overall_summary"] = "Very strong overall package."
        self.review.result_data = result_data
        self.review.save(
            update_fields=[
                "overall_rating",
                "overall_score_numeric",
                "result_data",
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
        self.assertIn("Very strong overall package.", updated.plain_text)
        review_row = Review.objects.get(object_id=updated.id)
        self.assertEqual(review_row.score, 5.0)
