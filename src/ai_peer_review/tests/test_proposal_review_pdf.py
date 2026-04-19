from django.test import override_settings
from rest_framework import status

from ai_peer_review.models import ProposalReview, ReviewStatus
from ai_peer_review.tests.test_proposal_review_views import ProposalReviewAPITests


@override_settings(CELERY_TASK_ALWAYS_EAGER=True)
class ProposalReviewPdfServiceTests(ProposalReviewAPITests):

    def test_pdf_export_get_returns_pdf_for_completed_review(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.COMPLETED,
            overall_rating="good",
            overall_score_numeric=2,
            overall_rationale="Rationale here.",
            result_data={
                "overall_summary": "Summary.",
                "categories": {
                    "funding_opportunity_fit": {
                        "score": "High",
                        "rationale": "Fit.",
                        "items": {
                            "fit_modality": {
                                "decision": "Yes",
                                "justification": "OK",
                            },
                        },
                    },
                },
            },
        )
        self.client.force_authenticate(self.moderator)
        url = f"/api/ai_peer_review/proposal-review/{pr.id}/pdf/"
        r = self.client.get(url)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    def test_pdf_export_rejects_pending_review(self):
        pr = ProposalReview.objects.create(
            created_by=self.moderator,
            unified_document=self.ud,
            grant=self.grant,
            status=ReviewStatus.PENDING,
            result_data={},
        )
        self.client.force_authenticate(self.moderator)
        url = f"/api/ai_peer_review/proposal-review/{pr.id}/pdf/"
        r = self.client.get(url)
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)
