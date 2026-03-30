from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import ProposalReview, RFPSummary
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from purchase.models import Grant, GrantApplication
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ProposalReviewAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "pr_moderator", moderator=True
        )
        self.user = create_random_authenticated_user("pr_user", moderator=False)
        self.grant_post = create_post(
            created_by=self.moderator, document_type=GRANT
        )
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Grant description for tests",
            status=Grant.OPEN,
        )
        self.prop_post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Test Proposal",
        )
        self.ud = self.prop_post.unified_document
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prop_post,
            applicant=self.user,
        )
        self.create_url = "/api/ai_peer_review/proposal-review/"
        self.detail_url = lambda rid: f"/api/ai_peer_review/proposal-review/{rid}/"
        self.grant_list_url = (
            f"/api/ai_peer_review/proposal-review/grant/{self.grant.id}/"
        )

    def test_create_requires_auth(self):
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_requires_editor_or_moderator(self):
        self.client.force_authenticate(self.user)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    @patch("ai_peer_review.tasks.process_proposal_review_task.delay")
    def test_create_returns_202_and_enqueues(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        pr = ProposalReview.objects.get(
            unified_document=self.ud, grant=self.grant
        )
        self.assertEqual(pr.created_by, self.moderator)

    @patch(
        "ai_peer_review.services.proposal_review_service.BedrockLLMService.invoke",
        return_value="not valid json {{{",
    )
    def test_proposal_review_task_marks_failed_on_bad_llm_output(self, _mock):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        pr = ProposalReview.objects.get(
            unified_document=self.ud, grant=self.grant
        )
        self.assertEqual(pr.status, ReviewStatus.FAILED)
        self.assertTrue(pr.error_message)

    def test_create_when_already_completed_returns_200(self):
        ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=9,
            result_data={"fundability": {"overall_score": "Medium"}},
        )
        self.client.force_authenticate(self.moderator)
        with patch("ai_peer_review.tasks.process_proposal_review_task.delay") as m:
            r = self.client.post(
                self.create_url,
                {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
                format="json",
            )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.json().get("already_exists"))
        m.assert_not_called()

    def test_create_wrong_document_type(self):
        paper_ud = create_post(
            created_by=self.moderator, document_type=DISCUSSION
        ).unified_document
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": paper_ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_without_grant_application(self):
        other_post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="Lonely",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {
                "unified_document_id": other_post.unified_document.id,
                "grant_id": self.grant.id,
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_detail(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={"fundability": {"overall_score": "High"}},
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()["overall_rating"], "good")
        self.assertEqual(r.json()["overall_score_numeric"], 10)

    def test_grant_comparison_lists_application(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="excellent",
            overall_score_numeric=15,
            result_data={
                "fundability": {"overall_score": "High"},
                "feasibility": {"overall_score": "High"},
                "novelty": {"overall_score": "High"},
                "impact": {"overall_score": "High"},
                "reproducibility": {"overall_score": "High"},
            },
        )
        RFPSummary.objects.create(
            grant=self.grant,
            created_by=self.moderator,
            status=ReviewStatus.COMPLETED,
            summary_content="Brief",
            executive_comparison_summary="Exec text",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.grant_list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertEqual(data["grant_id"], self.grant.id)
        self.assertEqual(len(data["proposals"]), 1)
        row = data["proposals"][0]
        self.assertEqual(row["review_id"], pr.id)
        self.assertEqual(row["fundability"], "High")
        self.assertEqual(data["executive_summary"], "Exec text")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RFPSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "rfp_mod", moderator=True
        )
        self.grant_post = create_post(
            created_by=self.moderator, document_type=GRANT
        )
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Org",
            description="RFP body",
            status=Grant.OPEN,
        )
        self.summary_url = "/api/ai_peer_review/rfp-summary/"
        self.summary_get = f"/api/ai_peer_review/rfp-summary/{self.grant.id}/"

    @patch("ai_peer_review.tasks.process_rfp_summary_task.delay")
    def test_post_rfp_summary(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.summary_url, {"grant_id": self.grant.id}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        self.assertTrue(
            RFPSummary.objects.filter(grant_id=self.grant.id).exists()
        )

    def test_get_rfp_summary_404_when_missing(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.summary_get)
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class GrantExecutiveSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "exec_mod", moderator=True
        )
        self.user = create_random_authenticated_user("exec_user")
        self.grant_post = create_post(
            created_by=self.moderator, document_type=GRANT
        )
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("8000.00"),
            currency="USD",
            organization="Funder",
            description="Grant",
            status=Grant.OPEN,
        )
        self.prop_post = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="P1",
        )
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.prop_post,
            applicant=self.user,
        )
        ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.prop_post.unified_document,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={
                "editorial_summary": {"consensus_summary": "Solid work."},
                "fundability": {"overall_score": "High"},
                "feasibility": {"overall_score": "Medium"},
                "novelty": {"overall_score": "High"},
                "impact": {"overall_score": "High"},
                "reproducibility": {"overall_score": "Medium"},
            },
        )
        self.url = "/api/ai_peer_review/grant-executive-summary/"

    @patch(
        "ai_peer_review.services.rfp_summary_service.BedrockLLMService.invoke",
        return_value="## Summary\nCompared proposals.",
    )
    def test_post_executive_summary(self, _mock_invoke):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.url, {"grant_id": self.grant.id}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertIn("executive_summary", data)
        self.assertIn("Compared proposals", data["executive_summary"])
        rs = RFPSummary.objects.get(grant=self.grant)
        self.assertIn("Compared proposals", rs.executive_comparison_summary)

    def test_post_executive_no_reviews(self):
        ProposalReview.objects.all().delete()
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.url, {"grant_id": self.grant.id}, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
