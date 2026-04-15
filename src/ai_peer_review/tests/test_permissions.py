from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from ai_peer_review.models import ProposalReview
from ai_peer_review.permissions import AIPeerReviewPermission
from paper.tests.helpers import create_paper
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


class AIPeerReviewPermissionTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.permission = AIPeerReviewPermission()
        self.view = object()

    def test_has_permission_requires_authentication(self):
        anon_req = self.factory.get("/")
        anon_req.user = AnonymousUser()
        self.assertFalse(self.permission.has_permission(anon_req, self.view))

        request = self.factory.get("/")
        request.user = create_random_authenticated_user("perm_user")
        self.assertTrue(self.permission.has_permission(request, self.view))

    def test_has_object_permission_proposal_review_matches_access(self):
        author = create_random_authenticated_user("perm_author")
        stranger = create_random_authenticated_user("perm_stranger")
        paper = create_paper(uploaded_by=author)
        review = ProposalReview.objects.create(
            unified_document=paper.unified_document,
            grant=None,
        )
        ok_req = self.factory.get("/")
        ok_req.user = author
        self.assertTrue(
            self.permission.has_object_permission(ok_req, self.view, review),
        )
        bad_req = self.factory.get("/")
        bad_req.user = stranger
        self.assertFalse(
            self.permission.has_object_permission(bad_req, self.view, review),
        )

    def test_has_object_permission_grant_owner(self):
        owner = create_random_authenticated_user("perm_g_owner")
        stranger = create_random_authenticated_user("perm_g_stranger")
        post = create_post(created_by=owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=owner,
            unified_document=post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Org",
            description="D",
            status=Grant.OPEN,
        )
        ok_req = self.factory.get("/")
        ok_req.user = owner
        self.assertTrue(
            self.permission.has_object_permission(ok_req, self.view, grant),
        )
        bad_req = self.factory.get("/")
        bad_req.user = stranger
        self.assertFalse(
            self.permission.has_object_permission(bad_req, self.view, grant),
        )
