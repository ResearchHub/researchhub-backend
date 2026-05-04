import json
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from rest_framework.renderers import JSONRenderer

from ai_peer_review.models import (
    KeyInsightItemType,
    ProposalKeyInsight,
    ProposalKeyInsightItem,
    ProposalReview,
    Status,
)
from ai_peer_review.serializers import ProposalReviewSerializer
from ai_peer_review.services.proposal_key_insights_service import (
    ProposalKeyInsightsService,
)
from researchhub_comment.constants.rh_comment_thread_types import COMMUNITY_REVIEW
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from review.models import Review
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

    def _create_comment(
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

    def _create_review(
        self, comment: RhCommentModel, *, is_assessed: bool = True
    ) -> Review:
        return Review.objects.create(
            content_type=self.comment_ct,
            object_id=comment.id,
            unified_document=self.ud,
            created_by=self.reviewer,
            score=3.0,
            is_assessed=is_assessed,
        )

    def test_includes_assessed_community_review(self):
        t = self._thread()
        c = self._create_comment(t, "ASSESSED_TEXT")
        self._create_review(c, is_assessed=True)
        out = ProposalKeyInsightsService._get_rhf_endorsed_human_reviews(self.ud)
        self.assertIn("ASSESSED_TEXT", out)
        self.assertIn("Reviewer 1", out)

    def test_excludes_comment_with_no_review_row(self):
        t = self._thread()
        self._create_comment(t, "NO_REVIEW")
        out = ProposalKeyInsightsService._get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("NO_REVIEW", out)

    def test_excludes_unassessed_review(self):
        t = self._thread()
        c = self._create_comment(t, "NOT_ASSESSED")
        self._create_review(c, is_assessed=False)
        out = ProposalKeyInsightsService._get_rhf_endorsed_human_reviews(self.ud)
        self.assertNotIn("NOT_ASSESSED", out)


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
            status=Status.COMPLETED,
            result_data={},
        )

    def _mock_llm(self, mock_bedrock, raw: str) -> None:
        inst = mock_bedrock.return_value
        inst.model_id = "us.test.model"
        inst.invoke.return_value = raw

    def test_success_saves_tldr_and_items(self, mock_bedrock, _mock_proposal_markdown):
        self._mock_llm(mock_bedrock, _CANNED_JSON)
        ki = ProposalKeyInsightsService().run(self.review.id, force=True)
        ki.refresh_from_db()
        self.assertEqual(ki.status, Status.COMPLETED)
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
        ProposalKeyInsightsService().run(self.review.id, force=True)
        v2 = json.dumps(
            {
                "tldr": "Replaced one. Two. Three.",
                "strengths": [{"label": "OnlyS", "description": "D"}],
                "weaknesses": [],
            }
        )
        self._mock_llm(mock_bedrock, v2)
        ProposalKeyInsightsService().run(self.review.id, force=True)
        ki = ProposalKeyInsight.objects.get(proposal_review=self.review)
        self.assertIn("Replaced", ki.tldr)
        self.assertEqual(ki.items.count(), 1)
        self.assertEqual(ki.items.get().label, "OnlyS")

    def test_invalid_json_marks_failed_and_does_not_clear_previous_items(
        self, mock_bedrock, _mock_proposal_markdown
    ):
        self._mock_llm(mock_bedrock, _CANNED_JSON)
        ProposalKeyInsightsService().run(self.review.id, force=True)
        self.assertEqual(
            ProposalKeyInsightItem.objects.filter(
                key_insight__proposal_review=self.review
            ).count(),
            3,
        )
        self._mock_llm(mock_bedrock, "not valid json {")
        ProposalKeyInsightsService().run(self.review.id, force=True)
        ki = ProposalKeyInsight.objects.get(proposal_review=self.review)
        self.assertEqual(ki.status, Status.FAILED)
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
            status=Status.COMPLETED,
            result_data={},
        )
        self.ki = ProposalKeyInsight.objects.create(
            proposal_review=self.review,
            status=Status.COMPLETED,
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
        self.assertIn("key_insight", as_json)
        self.assertIsNotNone(as_json["key_insight"])
