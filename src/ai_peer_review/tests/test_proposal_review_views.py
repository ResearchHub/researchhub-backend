from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from ai_peer_review.constants import ReviewStatus
from ai_peer_review.models import (
    EditorialFeedback,
    ProposalReview,
    ReportEntitlement,
    RFPSummary,
)
from purchase.models import Grant, GrantApplication, Purchase
from purchase.related_models.fundraise_model import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ProposalReviewAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "pr_moderator", moderator=True
        )
        self.user = create_random_authenticated_user("pr_user", moderator=False)
        self.grant_post = create_post(created_by=self.moderator, document_type=GRANT)
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
        pr = ProposalReview.objects.get(unified_document=self.ud, grant=self.grant)
        self.assertEqual(pr.created_by, self.moderator)

    @patch(
        "ai_peer_review.services.proposal_review_service.fetch_proposal_review_web_context",
        return_value="",
    )
    @patch(
        "ai_peer_review.services.proposal_review_service.build_researcher_external_context",
        return_value="EXTERNAL_RESEARCHER_CTX_MARKER",
    )
    @patch(
        "ai_peer_review.services.proposal_review_service.BedrockLLMService.invoke",
        return_value="not valid json {{{",
    )
    def test_proposal_review_task_marks_failed_on_bad_llm_output(
        self, mock_invoke, _ext, _web
    ):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        pr = ProposalReview.objects.get(unified_document=self.ud, grant=self.grant)
        self.assertEqual(pr.status, ReviewStatus.FAILED)
        self.assertTrue(pr.error_message)
        call_args = mock_invoke.call_args
        self.assertIsNotNone(call_args)
        user_prompt = call_args[0][1]
        self.assertIn("EXTERNAL RESEARCHER CONTEXT", user_prompt)
        self.assertIn("EXTERNAL_RESEARCHER_CTX_MARKER", user_prompt)

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
        self.assertIn("editorial_feedback", row)
        self.assertIsNone(row["editorial_feedback"])

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
        ProposalReview.objects.create(
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
            "fundability_expert": "high",
            "feasibility_expert": "medium",
            "novelty_expert": "low",
            "impact_expert": "high",
            "reproducibility_expert": "medium",
            "expert_insights": "Strong team.",
        }
        url = f"/api/ai_peer_review/editorial-feedback/{self.ud.id}/"
        r = self.client.post(url, body, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        fid = r.json()["id"]
        r2 = self.client.get(self.grant_list_url)
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        row = r2.json()["proposals"][0]
        self.assertIsNotNone(row["editorial_feedback"])
        self.assertEqual(row["editorial_feedback"]["id"], fid)

        r3 = self.client.patch(
            url,
            {"expert_insights": "Updated."},
            format="json",
        )
        self.assertEqual(r3.status_code, status.HTTP_200_OK)
        self.assertEqual(r3.json()["expert_insights"], "Updated.")

    def test_editorial_feedback_visible_to_entitled_user_on_detail(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=10,
            result_data={},
        )
        EditorialFeedback.objects.create(
            unified_document=self.ud,
            created_by=self.moderator,
            updated_by=self.moderator,
            fundability_expert="high",
            feasibility_expert="high",
            novelty_expert="high",
            impact_expert="high",
            reproducibility_expert="high",
            expert_insights="Note.",
        )
        buyer = create_random_authenticated_user("pr_edit_viewer")
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
        self.assertEqual(r.json()["editorial_feedback"]["expert_insights"], "Note.")

    def test_get_detail_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/ai_peer_review/proposal-review/999999999/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_grant_comparison_grant_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/ai_peer_review/proposal-review/grant/999999999/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_unified_document_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": 999999999, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_grant_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": 999999999},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_grant_invalid_unified_document_type(self):
        bad_ud = ResearchhubUnifiedDocument.objects.create(document_type=DISCUSSION)
        bad_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=bad_ud,
            amount=Decimal("1.00"),
            currency="USD",
            organization="X",
            description="Y",
            status=Grant.OPEN,
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": bad_grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("ai_peer_review.tasks.process_proposal_review_task.delay")
    def test_create_without_grant_id(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        pr = ProposalReview.objects.get(unified_document=self.ud, grant__isnull=True)
        self.assertEqual(pr.status, ReviewStatus.PENDING)

    @patch("ai_peer_review.tasks.process_proposal_review_task.delay")
    def test_create_when_pending_returns_202_without_re_enqueuing(self, mock_delay):
        ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.PENDING,
        )
        self.client.force_authenticate(self.moderator)
        mock_delay.reset_mock()
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_not_called()

    @patch("ai_peer_review.tasks.process_proposal_review_task.delay")
    def test_create_when_failed_resets_and_re_enqueues(self, mock_delay):
        ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.FAILED,
            error_message="bad",
            result_data={"x": 1},
            overall_rating="poor",
            overall_score_numeric=1,
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            self.create_url,
            {"unified_document_id": self.ud.id, "grant_id": self.grant.id},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        pr = ProposalReview.objects.get(unified_document=self.ud, grant=self.grant)
        self.assertEqual(pr.status, ReviewStatus.PENDING)
        self.assertEqual(pr.error_message, "")

    def test_pdf_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get("/api/ai_peer_review/proposal-review/999999999/pdf/")
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_pdf_incomplete_returns_400(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.PENDING,
            result_data={},
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(f"/api/ai_peer_review/proposal-review/{pr.id}/pdf/")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pdf_forbidden_for_stranger(self):
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
        other = create_random_authenticated_user("pr_pdf_stranger")
        self.client.force_authenticate(other)
        r = self.client.get(f"/api/ai_peer_review/proposal-review/{pr.id}/pdf/")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_editorial_unified_document_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            "/api/ai_peer_review/editorial-feedback/999999999/",
            {
                "fundability_expert": "high",
                "feasibility_expert": "high",
                "novelty_expert": "high",
                "impact_expert": "high",
                "reproducibility_expert": "high",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_editorial_wrong_document_type(self):
        paper_ud = create_post(
            created_by=self.moderator, document_type=DISCUSSION
        ).unified_document
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            f"/api/ai_peer_review/editorial-feedback/{paper_ud.id}/",
            {
                "fundability_expert": "high",
                "feasibility_expert": "high",
                "novelty_expert": "high",
                "impact_expert": "high",
                "reproducibility_expert": "high",
            },
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_editorial_put_full_replace(self):
        self.client.force_authenticate(self.moderator)
        url = f"/api/ai_peer_review/editorial-feedback/{self.ud.id}/"
        create_body = {
            "fundability_expert": "high",
            "feasibility_expert": "medium",
            "novelty_expert": "low",
            "impact_expert": "high",
            "reproducibility_expert": "medium",
            "expert_insights": "First.",
        }
        r = self.client.post(url, create_body, format="json")
        self.assertEqual(r.status_code, status.HTTP_201_CREATED)
        put_body = {
            "fundability_expert": "low",
            "feasibility_expert": "low",
            "novelty_expert": "low",
            "impact_expert": "low",
            "reproducibility_expert": "low",
            "expert_insights": "Replaced.",
        }
        r2 = self.client.put(url, put_body, format="json")
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertEqual(r2.json()["expert_insights"], "Replaced.")
        self.assertEqual(r2.json()["fundability_expert"], "low")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RFPSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("rfp_mod", moderator=True)
        self.grant_post = create_post(created_by=self.moderator, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Org",
            description="RFP body",
            status=Grant.OPEN,
        )
        self.rfp_grant_url = f"/api/ai_peer_review/rfp/{self.grant.id}/"

    @patch("ai_peer_review.tasks.process_rfp_summary_task.delay")
    def test_post_rfp_summary(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.rfp_grant_url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        self.assertTrue(RFPSummary.objects.filter(grant_id=self.grant.id).exists())

    def test_get_rfp_summary_404_when_missing(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.rfp_grant_url)
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_rfp_summary_when_exists(self):
        RFPSummary.objects.create(
            grant=self.grant,
            created_by=self.moderator,
            status=ReviewStatus.COMPLETED,
            summary_content="Stored brief",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.rfp_grant_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.json()["summary_content"], "Stored brief")

    @patch("ai_peer_review.tasks.process_rfp_summary_task.delay")
    def test_post_rfp_summary_already_completed_returns_200(self, mock_delay):
        RFPSummary.objects.create(
            grant=self.grant,
            created_by=self.moderator,
            status=ReviewStatus.COMPLETED,
            summary_content="Done",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.rfp_grant_url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertTrue(r.json().get("already_exists"))
        mock_delay.assert_not_called()

    @patch("ai_peer_review.tasks.process_rfp_summary_task.delay")
    def test_post_rfp_summary_force_requeues(self, mock_delay):
        RFPSummary.objects.create(
            grant=self.grant,
            created_by=self.moderator,
            status=ReviewStatus.COMPLETED,
            summary_content="Done",
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.rfp_grant_url, {"force": True}, format="json")
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()

    def test_post_rfp_summary_grant_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            "/api/ai_peer_review/rfp/999999999/",
            {},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_post_rfp_summary_grant_not_grant_document(self):
        bad_ud = ResearchhubUnifiedDocument.objects.create(document_type=DISCUSSION)
        bad_grant = Grant.objects.create(
            created_by=self.moderator,
            unified_document=bad_ud,
            amount=Decimal("1.00"),
            currency="USD",
            organization="X",
            description="Y",
            status=Grant.OPEN,
        )
        url = f"/api/ai_peer_review/rfp/{bad_grant.id}/"
        self.client.force_authenticate(self.moderator)
        r = self.client.post(url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)


class GrantExecutiveSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("exec_mod", moderator=True)
        self.user = create_random_authenticated_user("exec_user")
        self.grant_post = create_post(created_by=self.moderator, document_type=GRANT)
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
        self.url = f"/api/ai_peer_review/rfp/{self.grant.id}/executive-summary/"

    @patch(
        "ai_peer_review.services.rfp_summary_service.BedrockLLMService.invoke",
        return_value="## Summary\nCompared proposals.",
    )
    def test_post_executive_summary(self, _mock_invoke):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertIn("executive_summary", data)
        self.assertIn("Compared proposals", data["executive_summary"])
        rs = RFPSummary.objects.get(grant=self.grant)
        self.assertIn("Compared proposals", rs.executive_comparison_summary)

    def test_post_executive_no_reviews(self):
        ProposalReview.objects.all().delete()
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_executive_grant_not_found(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(
            "/api/ai_peer_review/rfp/999999999/executive-summary/",
            {},
            format="json",
        )
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    @patch(
        "ai_peer_review.views.proposal_review_views.run_executive_comparison",
        side_effect=RuntimeError("upstream failure"),
    )
    def test_post_executive_summary_502_on_unexpected_error(self, _mock):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_502_BAD_GATEWAY)
