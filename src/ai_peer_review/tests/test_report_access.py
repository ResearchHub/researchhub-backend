from decimal import Decimal

from django.test import TestCase

from ai_peer_review.models import ProposalReview, RFPSummary
from ai_peer_review.services.report_access import (
    user_can_view_proposal_review,
    user_can_view_rfp_summary,
)
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class ReportAccessTests(TestCase):

    def test_author_can_view_own_proposal_review(self):
        author = create_random_authenticated_user("ra_author")
        preregistration_post = create_post(
            created_by=author,
            document_type=PREREGISTRATION,
        )
        review = ProposalReview.objects.create(
            unified_document=preregistration_post.unified_document,
            grant=None,
        )
        self.assertTrue(user_can_view_proposal_review(author, review))

    def test_grant_creator_can_view_linked_review(self):
        grant_owner = create_random_authenticated_user("ra_grant_owner")
        proposal_author = create_random_authenticated_user("ra_proposal_author")
        stranger = create_random_authenticated_user("ra_grant_stranger")
        post = create_post(created_by=grant_owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=grant_owner,
            unified_document=post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Test Org",
            description="Test",
            status=Grant.OPEN,
        )
        preregistration_post = create_post(
            created_by=proposal_author,
            document_type=PREREGISTRATION,
        )
        review = ProposalReview.objects.create(
            unified_document=preregistration_post.unified_document,
            grant=grant,
        )
        self.assertTrue(user_can_view_proposal_review(grant_owner, review))
        self.assertTrue(user_can_view_proposal_review(proposal_author, review))
        self.assertFalse(user_can_view_proposal_review(stranger, review))

    def test_rfp_summary_access(self):
        owner = create_random_authenticated_user("ra_rfp_owner")
        stranger = create_random_authenticated_user("ra_rfp_stranger")
        worker = create_random_authenticated_user("ra_rfp_worker")
        post = create_post(created_by=owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=owner,
            unified_document=post.unified_document,
            amount=Decimal("200.00"),
            currency="USD",
            organization="O",
            description="D",
            status=Grant.OPEN,
        )
        summary = RFPSummary.objects.create(grant=grant, created_by=worker)
        self.assertTrue(user_can_view_rfp_summary(owner, summary))
        self.assertFalse(user_can_view_rfp_summary(stranger, summary))
