"""Tests for proposal key insights (RHF human-review filter, service, CLI)."""

import json
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from rest_framework.renderers import JSONRenderer

from ai_peer_review.models import (
    KeyInsightItemType,
    ProposalKeyInsight,
    ProposalKeyInsightItem,
    ProposalReview,
    ReviewStatus,
)
from ai_peer_review.serializers import ProposalReviewSerializer
from ai_peer_review.services.proposal_key_insights_service import (
    _get_rhf_endorsed_human_reviews,
    run_proposal_key_insights,
)
from purchase.models import Purchase
from reputation.models import Bounty, BountySolution, Escrow
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.models import User
from user.related_models.user_model import FOUNDATION_EMAIL
from user.tests.helpers import create_random_authenticated_user

_CANNED_JSON = json.dumps(
    {
        "tldr": "First. Second. Third.",
        "strengths": [
            {"label": "Strong A", "description": "Desc A."},
            {"label": "Strong B", "description": "Desc B."},
        ],
        "weaknesses": [
            {"label": "Weak X", "description": "Desc X."},
        ],
    }
)


def _quill(text: str) -> dict:
    return {"ops": [{"insert": text}]}


class ProposalKeyInsightsRhfHumanReviewsFilterTests(TestCase):
    def setUp(self):
        self.reviewer = create_random_authenticated_user("ki_reviewer")
        self.other = create_random_authenticated_user("ki_other")
        self.rhf, _ = User.objects.get_or_create(
            email=FOUNDATION_EMAIL,
            defaults={
                "username": "rhf_foundation_key_insights",
                "first_name": "RHF",
                "last_name": "Foundation",
            },
        )
        self.post = create_post(
            created_by=self.other,
            document_type=PREREGISTRATION,
            title="Proposal for key insight filter tests",
        )
        self.ud = self.post.unified_document
        self.comment_ct = ContentType.objects.get_for_model(RhCommentModel)

    def _thread(self) -> RhCommentThreadModel:
        return RhCommentThreadModel.objects.create(
            content_object=self.post,
            created_by=self.other,
            updated_by=self.other,
        )

    def _comment(
        self,
        thread: RhCommentThreadModel,
        body: str,
        user=None,
    ) -> RhCommentModel:
        u = user or self.reviewer
        return RhCommentModel.objects.create(
            comment_content_json=_quill(body),
            thread=thread,
            created_by=u,
            updated_by=u,
            comment_type=COMMUNITY_REVIEW,
        )

    def _rhf_bounty(
        self,
        comment: RhCommentModel,
        *,
        created_by: User,
        sol_status: str,
        awarded_amount: Decimal = Decimal("10"),
    ) -> Bounty:
        escrow = Escrow.objects.create(
            hold_type=Escrow.BOUNTY,
            status=Escrow.PENDING,
            amount_holding=Decimal("20"),
            content_type=self.comment_ct,
            object_id=comment.id,
            created_by=created_by,
        )
        bounty = Bounty.objects.create(
            bounty_type=Bounty.Type.REVIEW,
            amount=Decimal("20"),
            created_by=created_by,
            item_content_type=self.comment_ct,
            item_object_id=comment.id,
            escrow=escrow,
            unified_document=self.ud,
        )
        BountySolution.objects.create(
            bounty=bounty,
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=comment.id,
            status=sol_status,
            awarded_amount=awarded_amount,
        )
        return bounty

    def _rhf_tip(self, comment: RhCommentModel) -> None:
        Purchase.objects.create(
            user=self.rhf,
            content_type=self.comment_ct,
            object_id=comment.id,
            amount="1",
            paid_status=Purchase.PAID,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
        )

    def test_includes_rhf_bounty_awarded_with_positive_amount(self):
        t = self._thread()
        c = self._comment(t, "MARK_AWARDED_OK")
        self._rhf_bounty(
            c, created_by=self.rhf, sol_status=BountySolution.Status.AWARDED
        )
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertIn("MARK_AWARDED_OK", out)
        self.assertIn("Reviewer 1", out)

    def test_includes_rhf_purchase_tip(self):
        t = self._thread()
        c = self._comment(t, "MARK_TIP_OK")
        self._rhf_tip(c)
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertIn("MARK_TIP_OK", out)

    def test_excludes_unendorsed_comment(self):
        t = self._thread()
        self._comment(t, "MARK_EXCLUDED_PLAIN")
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("MARK_EXCLUDED_PLAIN", out)

    def test_excludes_non_rhf_bounty_even_if_awarded(self):
        t = self._thread()
        c = self._comment(t, "MARK_BOUNTY_OTHER_USER")
        self._rhf_bounty(
            c, created_by=self.other, sol_status=BountySolution.Status.AWARDED
        )
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("MARK_BOUNTY_OTHER_USER", out)

    def test_excludes_submitted_solution_rhf_bounty(self):
        t = self._thread()
        c = self._comment(t, "MARK_SUBMITTED")
        self._rhf_bounty(
            c, created_by=self.rhf, sol_status=BountySolution.Status.SUBMITTED
        )
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("MARK_SUBMITTED", out)

    def test_excludes_tip_from_non_rhf(self):
        t = self._thread()
        c = self._comment(t, "MARK_NONRHF_TIP")
        Purchase.objects.create(
            user=self.other,
            content_type=self.comment_ct,
            object_id=c.id,
            amount="1",
            paid_status=Purchase.PAID,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
        )
        out = _get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("MARK_NONRHF_TIP", out)


@patch(
    "ai_peer_review.services.proposal_key_insights_service.get_proposal_markdown",
    return_value="# Proposal",
)
@patch("ai_peer_review.services.proposal_key_insights_service.BedrockLLMService")
class RunProposalKeyInsightsServiceTests(TestCase):
    def setUp(self):
        User.objects.get_or_create(
            email=FOUNDATION_EMAIL,
            defaults={
                "username": "rhf_foundation_ki_run",
                "first_name": "RHF",
                "last_name": "Foundation",
            },
        )
        self.user = create_random_authenticated_user("ki_run")
        self.post = create_post(
            created_by=self.user, document_type=PREREGISTRATION, title="KIS run"
        )
        self.ud = self.post.unified_document
        self.review = ProposalReview.objects.create(
            created_by=self.user,
            unified_document=self.ud,
            grant_id=None,
            status=ReviewStatus.COMPLETED,
            result_data={},
        )

    def _mock_llm(self, mock_bedrock, raw: str) -> None:
        inst = mock_bedrock.return_value
        inst.model_id = "us.test.model"
        inst.invoke.return_value = raw

    def test_success_saves_tldr_and_items(self, mock_bedrock, _mock_proposal_markdown):
        self._mock_llm(mock_bedrock, _CANNED_JSON)
        ki = run_proposal_key_insights(self.review.id, force=True)
        ki.refresh_from_db()
        self.assertEqual(ki.status, ReviewStatus.COMPLETED)
        self.assertIn("First.", ki.tldr)
        self.assertEqual(ki.llm_model, "us.test.model")
        self.assertIsNotNone(ki.processing_time)
        st = list(
            ki.items.filter(item_type=KeyInsightItemType.STRENGTH).order_by(
                "order", "id"
            )
        )
        wk = list(
            ki.items.filter(item_type=KeyInsightItemType.WEAKNESS).order_by(
                "order", "id"
            )
        )
        self.assertEqual([x.label for x in st], ["Strong A", "Strong B"])
        self.assertEqual([x.order for x in st], [0, 1])
        self.assertEqual([x.label for x in wk], ["Weak X"])
        self.assertEqual([x.order for x in wk], [0])

    def test_force_replaces_items_and_tldr(self, mock_bedrock, _mock_proposal_markdown):
        self._mock_llm(mock_bedrock, _CANNED_JSON)
        run_proposal_key_insights(self.review.id, force=True)
        v2 = json.dumps(
            {
                "tldr": "Replaced one. Two. Three.",
                "strengths": [{"label": "OnlyS", "description": "D"}],
                "weaknesses": [],
            }
        )
        self._mock_llm(mock_bedrock, v2)
        run_proposal_key_insights(self.review.id, force=True)
        ki = ProposalKeyInsight.objects.get(proposal_review=self.review)
        self.assertIn("Replaced", ki.tldr)
        self.assertEqual(ki.items.count(), 1)
        self.assertEqual(ki.items.get().label, "OnlyS")

    def test_invalid_json_marks_failed_and_does_not_clear_previous_items(
        self, mock_bedrock, _mock_proposal_markdown
    ):
        self._mock_llm(mock_bedrock, _CANNED_JSON)
        run_proposal_key_insights(self.review.id, force=True)
        self.assertEqual(
            ProposalKeyInsightItem.objects.filter(
                key_insight__proposal_review=self.review
            ).count(),
            3,
        )
        self._mock_llm(mock_bedrock, "not valid json {")
        run_proposal_key_insights(self.review.id, force=True)
        ki = ProposalKeyInsight.objects.get(proposal_review=self.review)
        self.assertEqual(ki.status, ReviewStatus.FAILED)
        self.assertTrue(ki.error_message)
        self.assertEqual(
            ProposalKeyInsightItem.objects.filter(
                key_insight__proposal_review=self.review
            ).count(),
            3,
        )


class ProposalKeyInsightSerializerTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("ki_ser")
        self.post = create_post(created_by=self.user, document_type=PREREGISTRATION)
        self.review = ProposalReview.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            grant_id=None,
            status=ReviewStatus.COMPLETED,
            result_data={},
        )
        self.ki = ProposalKeyInsight.objects.create(
            proposal_review=self.review,
            status=ReviewStatus.COMPLETED,
            tldr="A short summary here.",
        )
        ProposalKeyInsightItem.objects.create(
            key_insight=self.ki,
            item_type=KeyInsightItemType.STRENGTH,
            label="A label",
            description="Desc",
            order=0,
        )

    def test_proposal_review_serializer_includes_key_insight(self):
        data = ProposalReviewSerializer(
            self.review,
        ).data
        self.assertIn("key_insight", data)
        self.assertEqual(
            data["key_insight"]["tldr"],
            "A short summary here.",
        )
        self.assertEqual(
            [x["label"] for x in data["key_insight"]["items"]],
            ["A label"],
        )

    def test_json_round_trip_includes_key_insight(self):
        # Mirrors researchhub_document use of JSONRenderer for proposal review payloads
        data = ProposalReviewSerializer(self.review).data
        as_json = json.loads(JSONRenderer().render(data).decode())
        self.assertIn("key_insight", as_json)
        self.assertIsNotNone(as_json["key_insight"])
