from django.test import SimpleTestCase

from ai_peer_review.models import (
    EditorialFeedback,
    ProposalReview,
    ReportEntitlement,
    RFPSummary,
)


class AiPeerReviewModelsSmokeTest(SimpleTestCase):
    def test_db_tables_match_reference(self):
        self.assertEqual(
            ProposalReview._meta.db_table, "ai_peer_review_proposalreview"
        )
        self.assertEqual(RFPSummary._meta.db_table, "ai_peer_review_rfp_summary")
        self.assertEqual(
            ReportEntitlement._meta.db_table, "ai_peer_review_report_entitlement"
        )
        self.assertEqual(
            EditorialFeedback._meta.db_table, "ai_peer_review_editorial_feedback"
        )

    def test_proposal_review_meta_constraints(self):
        names = {c.name for c in ProposalReview._meta.constraints}
        self.assertEqual(
            names,
            {
                "ai_peer_review_pr_ud_grant_nn",
                "ai_peer_review_pr_ud_standalone",
            },
        )
