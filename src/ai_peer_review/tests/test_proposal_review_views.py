from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from ai_peer_review.constants import CATEGORY_KEYS
from ai_peer_review.models import ProposalReview, ReviewStatus, RFPSummary
from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ProposalReviewAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "prv_moderator", moderator=True
        )
        self.user = create_random_authenticated_user("prv_user", moderator=False)
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

    def test_create_requires_authentication(self):
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
    def test_create_enqueues_job_for_editor(self, mock_delay):
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

    def test_detail_visible_to_moderator_not_author_or_stranger(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=4,
            overall_rationale="Strong fit.",
            overall_confidence="High",
            result_data={
                "categories": {"overall_impact": {"score": 5}},
            },
        )
        self.client.force_authenticate(self.moderator)
        r_mod = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r_mod.status_code, status.HTTP_200_OK)
        self.assertEqual(r_mod.json()["overall_rating"], "good")

        self.client.force_authenticate(self.user)
        r_author = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r_author.status_code, status.HTTP_403_FORBIDDEN)

        stranger = create_random_authenticated_user("prv_stranger")
        self.client.force_authenticate(stranger)
        r_other = self.client.get(self.detail_url(pr.id))
        self.assertEqual(r_other.status_code, status.HTTP_403_FORBIDDEN)

    def test_grant_comparison_returns_application_row_for_authenticated_editor(self):
        ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="excellent",
            overall_score_numeric=5,
            result_data={
                "categories": {
                    "overall_impact": {"score": 5},
                    "importance_significance_innovation": {"score": 5},
                    "rigor_and_feasibility": {"score": 5},
                    "additional_review_criteria": {"score": 1},
                },
            },
        )
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.grant_list_url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        data = r.json()
        self.assertEqual(data["grant_id"], self.grant.id)
        self.assertEqual(len(data["proposals"]), 1)
        self.assertEqual(data["proposals"][0]["categories"]["overall_impact"], 5)
        self.assertEqual(
            data["proposals"][0]["categories"]["additional_review_criteria"],
            1,
        )

    def test_editorial_feedback_upsert_requires_editor(self):
        self.client.force_authenticate(self.user)
        url = f"/api/ai_peer_review/editorial-feedback/{self.ud.id}/"
        body = {
            "expert_insights": "Solid.",
            "categories": [
                {"category_code": k, "score": "high"} for k in CATEGORY_KEYS
            ],
        }
        r = self.client.post(url, body, format="json")
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.moderator)
        r2 = self.client.post(url, body, format="json")
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(r2.json()["categories"]), len(CATEGORY_KEYS))

    def test_editorial_feedback_patch_replaces_categories(self):
        url = f"/api/ai_peer_review/editorial-feedback/{self.ud.id}/"
        create_body = {
            "categories": [
                {"category_code": k, "score": "high"} for k in CATEGORY_KEYS
            ],
        }
        self.client.force_authenticate(self.moderator)
        self.client.post(url, create_body, format="json")
        patch_body = {
            "categories": [{"category_code": k, "score": "low"} for k in CATEGORY_KEYS],
        }
        r = self.client.patch(url, patch_body, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        for row in r.json()["categories"]:
            self.assertEqual(row["score"], "low")


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class RFPSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("prv_rfp_mod", moderator=True)
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
        self.rfp_url = f"/api/ai_peer_review/rfp/{self.grant.id}/"

    @patch("ai_peer_review.tasks.process_rfp_summary_task.delay")
    def test_post_starts_summary_job(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.rfp_url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        self.assertTrue(RFPSummary.objects.filter(grant_id=self.grant.id).exists())

    def test_get_returns_404_when_no_summary_yet(self):
        self.client.force_authenticate(self.moderator)
        r = self.client.get(self.rfp_url)
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)


class GrantExecutiveSummaryAPITests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user(
            "prv_exec_mod", moderator=True
        )
        self.user = create_random_authenticated_user("prv_exec_user")
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
            overall_score_numeric=4,
            result_data={
                "overall_summary": "Solid work across categories.",
                "categories": {
                    "overall_impact": {"score": 5},
                    "importance_significance_innovation": {"score": 5},
                    "rigor_and_feasibility": {"score": 3},
                    "additional_review_criteria": {"score": 1},
                },
            },
        )
        self.url = f"/api/ai_peer_review/rfp/{self.grant.id}/executive-summary/"

    @patch(
        "ai_peer_review.services.rfp_summary_service.BedrockLLMService.invoke",
        return_value="## Summary\nCompared proposals.",
    )
    def test_post_generates_executive_summary(self, _mock_invoke):
        self.client.force_authenticate(self.moderator)
        r = self.client.post(self.url, {}, format="json")
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn("Compared proposals", r.json()["executive_summary"])
        rs = RFPSummary.objects.get(grant=self.grant)
        self.assertIn("Compared proposals", rs.executive_comparison_summary)
        self.assertEqual(rs.status, ReviewStatus.COMPLETED)
