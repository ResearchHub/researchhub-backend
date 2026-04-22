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
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
)


class ReportAccessTests(TestCase):

    def test_proposal_review_visible_only_to_editor_or_moderator(self):
        author = create_random_authenticated_user("ra_author")
        editor, _hub = create_hub_editor("ra_editor", "ra_hub")
        moderator = create_random_authenticated_user("ra_mod", moderator=True)
        stranger = create_random_authenticated_user("ra_stranger")
        preregistration_post = create_post(
            created_by=author,
            document_type=PREREGISTRATION,
        )
        review = ProposalReview.objects.create(
            unified_document=preregistration_post.unified_document,
            grant=None,
        )
        self.assertFalse(user_can_view_proposal_review(author, review))
        self.assertFalse(user_can_view_proposal_review(stranger, review))
        self.assertTrue(user_can_view_proposal_review(editor, review))
        self.assertTrue(user_can_view_proposal_review(moderator, review))

    def test_proposal_review_not_visible_to_grant_or_proposal_creators(self):
        grant_owner = create_random_authenticated_user("ra_grant_owner")
        proposal_author = create_random_authenticated_user("ra_proposal_author")
        editor, _hub = create_hub_editor("ra_editor2", "ra_hub2")
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
        self.assertFalse(user_can_view_proposal_review(grant_owner, review))
        self.assertFalse(user_can_view_proposal_review(proposal_author, review))
        self.assertTrue(user_can_view_proposal_review(editor, review))

    def test_rfp_summary_visible_only_to_editor_or_moderator(self):
        owner = create_random_authenticated_user("ra_rfp_owner")
        stranger = create_random_authenticated_user("ra_rfp_stranger")
        worker = create_random_authenticated_user("ra_rfp_worker")
        editor, _hub = create_hub_editor("ra_rfp_editor", "ra_rfp_hub")
        moderator = create_random_authenticated_user("ra_rfp_mod", moderator=True)
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
        self.assertFalse(user_can_view_rfp_summary(owner, summary))
        self.assertFalse(user_can_view_rfp_summary(stranger, summary))
        self.assertTrue(user_can_view_rfp_summary(editor, summary))
        self.assertTrue(user_can_view_rfp_summary(moderator, summary))
