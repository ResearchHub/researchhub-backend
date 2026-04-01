from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import ProposalReview, ReportEntitlement, RFPSummary
from purchase.models import Purchase
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
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
        self.assertIn("editorial_feedbacks", row)
        self.assertEqual(row["editorial_feedbacks"], [])

    def test_get_detail_proposal_author_allowed(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={"fundability": {"overall_score": "High"}},
        )
        self.client.force_authenticate(self.user)
        r = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()["overall_rating"], "good")

    def test_get_detail_stranger_forbidden(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={},
        )
        other = create_random_authenticated_user("pr_stranger")
        self.client.force_authenticate(other)
        r = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_detail_entitlement_allows_viewer(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={},
        )
        buyer = create_random_authenticated_user("pr_buyer")
        uni = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        ct = ContentType.objects.get_for_model(Fundraise)
        fr = Fundraise.objects.create(
            created_by=buyer,
            status=Fundraise.CLOSED,
            unified_document=uni,
        )
        purchase = Purchase.objects.create(
            user=buyer,
            content_type=ct,
            object_id=fr.id,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status=Purchase.PAID,
            amount="1",
            purchase_method=Purchase.OFF_CHAIN,
        )
        ReportEntitlement.objects.create(
            user=buyer,
            proposal_review=pr,
            purchase=purchase,
        )
        self.client.force_authenticate(buyer)
        r = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r.status_code, status.HTTP_200_OK)

    def test_grant_comparison_forbidden_for_applicant(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={
                "fundability": {"overall_score": "High"},
                "feasibility": {"overall_score": "High"},
                "novelty": {"overall_score": "High"},
                "impact": {"overall_score": "High"},
                "reproducibility": {"overall_score": "High"},
            },
        )
        self.client.force_authenticate(self.user)
        r = self.client.get(self.grant_list_url)
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_grant_comparison_allowed_for_grant_owner(self):
        funder = create_random_authenticated_user("pr_funder")
        grant_post = create_post(created_by=funder, document_type=GRANT)
        g2 = Grant.objects.create(
            created_by=funder,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Funder Org",
            description="RFP",
            status=Grant.OPEN,
        )
        prop2 = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title="App",
        )
        GrantApplication.objects.create(
            grant=g2,
            preregistration_post=prop2,
            applicant=self.user,
        )
        pr2 = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=prop2.unified_document,
            grant=g2,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=11,
            result_data={
                "fundability": {"overall_score": "Medium"},
                "feasibility": {"overall_score": "High"},
                "novelty": {"overall_score": "High"},
                "impact": {"overall_score": "High"},
                "reproducibility": {"overall_score": "High"},
            },
        )
        self.client.force_authenticate(funder)
        url = f"/api/ai_peer_review/proposal-review/grant/{g2.id}/"
        r = self.client.get(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()["proposals"][0]["review_id"], pr2.id)

    def test_pdf_returns_file_when_complete(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={
                "editorial_summary": {"consensus_summary": "Ok."},
                "fundability": {"overall_score": "High", "overall_rationale": "x"},
                "feasibility": {"overall_score": "High"},
                "novelty": {"overall_score": "High"},
                "impact": {"overall_score": "High"},
                "reproducibility": {"overall_score": "High"},
            },
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(f"/api/ai_peer_review/proposal-review/{pr.id}/pdf/")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertGreater(len(r.content), 100)

    def test_editorial_feedback_create_and_listed_on_grant_row(self):
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
        body = {
            "proposal_review_id": pr.id,
            "fundability_expert": "high",
            "feasibility_expert": "medium",
            "novelty_expert": "low",
            "impact_expert": "high",
            "reproducibility_expert": "medium",
            "expert_insights": "Strong team.",
        }
        r = self.client.post(
            "/api/ai_peer_review/editorial-feedback/", body, format="json"
        )
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        fid = r.json()["id"]
        r2 = self.client.get(self.grant_list_url)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        row = r2.json()["proposals"][0]
        self.assertEqual(len(row["editorial_feedbacks"]), 1)
        self.assertEqual(row["editorial_feedbacks"][0]["id"], fid)

        r3 = self.client.patch(
            f"/api/ai_peer_review/editorial-feedback/{fid}/",
            {"expert_insights": "Updated."},
            format="json",
        )
        self.assertEqual(r3.status_code, status.HTTP_200_OK)
        self.assertEqual(r3.json()["expert_insights"], "Updated.")


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
