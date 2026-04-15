from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from ai_peer_review.models import ProposalReview, ReportEntitlement
from ai_peer_review.services.report_access import (
    is_editor_or_moderator,
    user_can_view_grant_comparison,
    user_can_view_proposal_review,
)
from paper.models import Paper
from paper.tests.helpers import create_paper
from purchase.models import Grant, Purchase
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


class ReportAccessTests(TestCase):
    def test_is_editor_or_moderator_anonymous(self):
        self.assertFalse(is_editor_or_moderator(AnonymousUser()))

    def test_is_editor_or_moderator_moderator(self):
        mod = create_random_authenticated_user("ra_mod", moderator=True)
        self.assertTrue(is_editor_or_moderator(mod))

    def test_is_editor_or_moderator_hub_editor(self):
        [editor, _hub] = create_hub_editor("ra_editor", "ra_hub")
        self.assertTrue(is_editor_or_moderator(editor))

    def test_author_can_view_own_proposal_review(self):
        author = create_random_authenticated_user("ra_author")
        paper = create_paper(uploaded_by=author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=None,
        )
        self.assertTrue(user_can_view_proposal_review(author, review))

    def test_stranger_cannot_view_without_entitlement(self):
        author = create_random_authenticated_user("ra_author2")
        stranger = create_random_authenticated_user("ra_stranger")
        paper = create_paper(uploaded_by=author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=None,
        )
        self.assertFalse(user_can_view_proposal_review(stranger, review))

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
        paper = create_paper(uploaded_by=proposal_author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=grant,
        )
        self.assertTrue(user_can_view_proposal_review(grant_owner, review))
        self.assertTrue(user_can_view_proposal_review(proposal_author, review))
        self.assertFalse(user_can_view_proposal_review(stranger, review))

    def test_paid_entitlement_allows_view(self):
        author = create_random_authenticated_user("ra_ent_author")
        buyer = create_random_authenticated_user("ra_buyer")
        paper = create_paper(uploaded_by=author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=None,
        )
        ct_paper = ContentType.objects.get_for_model(Paper)
        purchase = Purchase.objects.create(
            user=buyer,
            content_type=ct_paper,
            object_id=paper.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.PAID,
            amount="1",
            purchase_method=Purchase.OFF_CHAIN,
        )
        ReportEntitlement.objects.create(
            user=buyer,
            proposal_review=review,
            purchase=purchase,
        )
        self.assertTrue(user_can_view_proposal_review(buyer, review))

    def test_unpaid_entitlement_denies_view(self):
        author = create_random_authenticated_user("ra_ent_author2")
        buyer = create_random_authenticated_user("ra_buyer2")
        paper = create_paper(uploaded_by=author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=None,
        )
        ct_paper = ContentType.objects.get_for_model(Paper)
        purchase = Purchase.objects.create(
            user=buyer,
            content_type=ct_paper,
            object_id=paper.id,
            purchase_type=Purchase.BOOST,
            paid_status=Purchase.INITIATED,
            amount="1",
            purchase_method=Purchase.OFF_CHAIN,
        )
        ReportEntitlement.objects.create(
            user=buyer,
            proposal_review=review,
            purchase=purchase,
        )
        self.assertFalse(user_can_view_proposal_review(buyer, review))

    def test_grant_comparison_owner_and_moderator(self):
        owner = create_random_authenticated_user("ra_gc_owner")
        stranger = create_random_authenticated_user("ra_gc_stranger")
        mod = create_random_authenticated_user("ra_gc_mod", moderator=True)
        post = create_post(created_by=owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=owner,
            unified_document=post.unified_document,
            amount=Decimal("5000.00"),
            currency="USD",
            organization="Org",
            description="Desc",
            status=Grant.OPEN,
        )
        self.assertTrue(user_can_view_grant_comparison(owner, grant))
        self.assertTrue(user_can_view_grant_comparison(mod, grant))
        self.assertFalse(user_can_view_grant_comparison(stranger, grant))

    def test_grant_comparison_anonymous(self):
        owner = create_random_authenticated_user("ra_gc_anon_owner")
        post = create_post(created_by=owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=owner,
            unified_document=post.unified_document,
            amount=Decimal("100.00"),
            currency="USD",
            organization="O",
            description="D",
            status=Grant.OPEN,
        )
        self.assertFalse(user_can_view_grant_comparison(AnonymousUser(), grant))
