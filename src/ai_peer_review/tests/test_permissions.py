from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from ai_peer_review.models import ProposalReview, RFPSummary
from ai_peer_review.permissions import AIPeerReviewPermission
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


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
        self.assertFalse(self.permission.has_permission(request, self.view))

        editor, _hub = create_hub_editor("perm_editor", "perm_hub")
        editor_req = self.factory.get("/")
        editor_req.user = editor
        self.assertTrue(self.permission.has_permission(editor_req, self.view))

        mod_req = self.factory.get("/")
        mod_req.user = create_random_authenticated_user("perm_mod", moderator=True)
        self.assertTrue(self.permission.has_permission(mod_req, self.view))

    def test_has_object_permission_proposal_review_matches_access(self):
        author = create_random_authenticated_user("perm_author")
        stranger = create_random_authenticated_user("perm_stranger")
        editor, _hub = create_hub_editor("perm_obj_editor", "perm_obj_hub")
        preregistration_post = create_post(
            created_by=author,
            document_type=PREREGISTRATION,
        )
        review = ProposalReview.objects.create(
            unified_document=preregistration_post.unified_document,
            grant=None,
        )
        author_req = self.factory.get("/")
        author_req.user = author
        self.assertFalse(
            self.permission.has_object_permission(author_req, self.view, review),
        )
        editor_req = self.factory.get("/")
        editor_req.user = editor
        self.assertTrue(
            self.permission.has_object_permission(editor_req, self.view, review),
        )
        bad_req = self.factory.get("/")
        bad_req.user = stranger
        self.assertFalse(
            self.permission.has_object_permission(bad_req, self.view, review),
        )

    def test_has_object_permission_rfp_summary_matches_grant_access(self):
        owner = create_random_authenticated_user("perm_rfp_owner")
        stranger = create_random_authenticated_user("perm_rfp_stranger")
        worker = create_random_authenticated_user("perm_rfp_worker")
        editor, _hub = create_hub_editor("perm_rfp_editor", "perm_rfp_hub")
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
        summary = RFPSummary.objects.create(grant=grant, created_by=worker)

        owner_req = self.factory.get("/")
        owner_req.user = owner
        self.assertFalse(
            self.permission.has_object_permission(owner_req, self.view, summary),
        )
        editor_req = self.factory.get("/")
        editor_req.user = editor
        self.assertTrue(
            self.permission.has_object_permission(editor_req, self.view, summary),
        )
        bad_req = self.factory.get("/")
        bad_req.user = stranger
        self.assertFalse(
            self.permission.has_object_permission(bad_req, self.view, summary),
        )
