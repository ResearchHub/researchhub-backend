from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from purchase.models import Grant, GrantApplication
from researchhub_access_group.constants import VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.unified_document_share_link_model import (
    UnifiedDocumentShareLink,
)
from researchhub_document.services.unified_document_share_link_service import (
    UnifiedDocumentShareLinkService,
)
from user.tests.helpers import (
    create_hub_editor,
    create_random_authenticated_user,
    create_random_default_user,
    make_user_verified,
)


def _grant_post_body(*, is_public=None, **overrides):
    body = {
        "document_type": "GRANT",
        "full_src": "body",
        "renderable_text": (
            "sufficiently long body. sufficiently long body. "
            "sufficiently long body. sufficiently long body. "
            "sufficiently long body"
        ),
        "title": "sufficiently long title. sufficiently long title.",
        "grant_amount": 50000,
        "grant_currency": "USD",
        "grant_organization": "Test Foundation",
        "grant_description": "Test grant for research",
    }
    if is_public is not None:
        body["is_public"] = is_public
    body.update(overrides)
    return body


class CreatePrivateGrantTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.author = create_random_default_user("private_grant_author", moderator=True)
        make_user_verified(self.author)

    def test_grant_defaults_to_public(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/api/researchhubpost/",
            _grant_post_body(),
        )
        self.assertEqual(resp.status_code, 200)
        post_id = resp.data["id"]
        post = ResearchhubPost.objects.get(id=post_id)
        self.assertTrue(post.unified_document.is_public)

    def test_grant_can_be_created_private(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/api/researchhubpost/",
            _grant_post_body(is_public=False),
        )
        self.assertEqual(resp.status_code, 200)
        post_id = resp.data["id"]
        post = ResearchhubPost.objects.get(id=post_id)
        self.assertFalse(post.unified_document.is_public)
        self.assertEqual(post.unified_document.grants.count(), 1)


class PrivateGrantVisibilityTests(APITestCase):
    """Private grants must be hidden from users without permission across
    the post-detail, grant feed, and GrantViewSet surfaces."""

    def setUp(self):
        cache.clear()
        GrantApplication.objects.all().delete()
        Grant.objects.all().delete()
        ResearchhubPost.objects.filter(document_type=GRANT).delete()

        self.owner = create_random_authenticated_user("priv_grant_owner")
        self.other = create_random_authenticated_user("priv_grant_other")
        self.invitee = create_random_authenticated_user("priv_grant_invitee")
        self.moderator = create_random_authenticated_user(
            "priv_grant_mod", moderator=True
        )

        self.public_post = create_post(
            created_by=self.owner, document_type=GRANT, title="Public Grant"
        )
        self.public_grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=self.public_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="OrgPub",
            description="public",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

        self.private_post = create_post(
            created_by=self.owner, document_type=GRANT, title="Private Grant"
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save(update_fields=["is_public"])
        self.private_grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=self.private_post.unified_document,
            amount=Decimal("20000.00"),
            currency="USD",
            organization="OrgPriv",
            description="private",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

        ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        Permission.objects.create(
            content_type=ud_ct,
            object_id=self.private_post.unified_document_id,
            user=self.invitee,
            access_type=VIEWER,
        )

    def tearDown(self):
        cache.clear()

    def test_grant_feed_hides_private_from_unrelated_user(self):
        self.client.force_authenticate(self.other)
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertNotIn("Private Grant", titles)

    def test_grant_feed_hides_private_from_anonymous(self):
        cache.clear()
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertNotIn("Private Grant", titles)

    def test_grant_feed_shows_private_to_owner(self):
        """Owners see private grants on discovery via the ``:viewer-*`` segment."""
        self.client.force_authenticate(self.owner)
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertIn("Private Grant", titles)

    def test_grant_feed_shows_private_to_permitted_user(self):
        """Invitees with permission see private grants on their viewer segment."""
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertIn("Private Grant", titles)

    def test_grant_viewset_hides_private_from_unrelated_user(self):
        self.client.force_authenticate(self.other)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_grant_viewset_shows_private_to_owner(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_grant_viewset_shows_private_to_moderator(self):
        self.client.force_authenticate(self.moderator)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_grant_viewset_shows_private_to_hub_editor(self):
        editor, _ = create_hub_editor("priv_grant_editor", "priv_grant_hub")
        self.client.force_authenticate(editor)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_post_detail_shows_private_grant_to_moderator(self):
        self.client.force_authenticate(self.moderator)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_post_detail_shows_private_grant_to_hub_editor(self):
        editor, _ = create_hub_editor("priv_grant_editor_post", "priv_grant_hub_post")
        self.client.force_authenticate(editor)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_grant_viewset_shows_private_to_permitted_user(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)


class PrivatePreregistrationVisibilityTests(APITestCase):
    """Moderators and hub editors must be able to view private preregistration
    posts so they can moderate them; unrelated users still get a 404."""

    def setUp(self):
        cache.clear()
        self.owner = create_random_authenticated_user("priv_prereg_owner")
        self.other = create_random_authenticated_user("priv_prereg_other")
        self.moderator = create_random_authenticated_user(
            "priv_prereg_mod", moderator=True
        )

        self.private_post = create_post(
            created_by=self.owner,
            document_type=PREREGISTRATION,
            title="Private Prereg",
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save(update_fields=["is_public"])

    def tearDown(self):
        cache.clear()

    def test_post_detail_hides_private_prereg_from_unrelated_user(self):
        self.client.force_authenticate(self.other)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_post_detail_shows_private_prereg_to_owner(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_post_detail_shows_private_prereg_to_moderator(self):
        self.client.force_authenticate(self.moderator)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_post_detail_shows_private_prereg_to_hub_editor(self):
        editor, _ = create_hub_editor("priv_prereg_editor", "priv_prereg_hub")
        self.client.force_authenticate(editor)
        resp = self.client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(resp.status_code, 200)


def _proposal_body(**overrides):
    body = {
        "document_type": PREREGISTRATION,
        "full_src": "body",
        "renderable_text": (
            "sufficiently long body. sufficiently long body. "
            "sufficiently long body. sufficiently long body. "
            "sufficiently long body"
        ),
        "title": "sufficiently long title. sufficiently long title.",
    }
    body.update(overrides)
    return body


class PrivateGrantShareAndApplicationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.owner = create_random_authenticated_user("priv_rfp_owner")
        self.applicant = create_random_authenticated_user("priv_rfp_applicant")
        make_user_verified(self.applicant)

        self.rfp_post = create_post(
            created_by=self.owner, document_type=GRANT, title="Private RFP"
        )
        self.rfp_doc = self.rfp_post.unified_document
        self.rfp_doc.is_public = False
        self.rfp_doc.save(update_fields=["is_public"])
        self.grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=self.rfp_doc,
            amount=Decimal("20000.00"),
            currency="USD",
            organization="OrgPriv",
            description="private",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )
        self.token = (
            UnifiedDocumentShareLinkService()
            .create_or_get(self.rfp_doc.id, self.owner)[0]
            .token
        )

    def tearDown(self):
        cache.clear()

    def _own_proposal(self, *, is_public):
        post = create_post(created_by=self.applicant, document_type=PREREGISTRATION)
        post.unified_document.is_public = is_public
        post.unified_document.save(update_fields=["is_public"])
        return post

    def test_owner_can_create_share_link_for_private_rfp_via_api(self):
        # Arrange
        UnifiedDocumentShareLink.objects.all().delete()
        self.client.force_authenticate(self.owner)

        # Act
        resp = self.client.post(
            f"/api/researchhub_unified_document/{self.rfp_doc.id}/share_link/"
        )

        # Assert
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(resp.data["token"])

    def test_anonymous_user_can_view_private_rfp_with_token(self):
        # Act
        with_token = self.client.get(
            f"/api/researchhubpost/{self.rfp_post.id}/?st={self.token}"
        )
        without_token = self.client.get(f"/api/researchhubpost/{self.rfp_post.id}/")

        # Assert
        self.assertEqual(with_token.status_code, 200)
        self.assertEqual(with_token.data["title"], "Private RFP")
        self.assertEqual(without_token.status_code, 404)

    def test_token_does_not_expose_rfp_in_grant_feed_or_grant_list(self):
        # Arrange
        self.client.force_authenticate(self.applicant)

        # Act
        feed = self.client.get(f"/api/grant_feed/?st={self.token}")
        listing = self.client.get(f"/api/grant/?st={self.token}")
        detail = self.client.get(f"/api/grant/{self.grant.id}/?st={self.token}")

        # Assert
        feed_titles = [r["content_object"]["title"] for r in feed.data["results"]]
        self.assertNotIn("Private RFP", feed_titles)
        listed_ids = [g["id"] for g in listing.data["results"]]
        self.assertNotIn(self.grant.id, listed_ids)
        self.assertEqual(detail.status_code, 404)

    def test_link_recipient_can_apply_with_token(self):
        # Arrange
        proposal = self._own_proposal(is_public=False)
        self.client.force_authenticate(self.applicant)

        # Act
        without_token = self.client.post(
            f"/api/grant/{self.grant.id}/application/",
            {"preregistration_post_id": proposal.id},
        )
        with_token = self.client.post(
            f"/api/grant/{self.grant.id}/application/?st={self.token}",
            {"preregistration_post_id": proposal.id},
        )

        # Assert
        self.assertEqual(without_token.status_code, 404)
        self.assertEqual(with_token.status_code, 201)
        self.assertTrue(
            GrantApplication.objects.filter(
                grant=self.grant, preregistration_post=proposal
            ).exists()
        )

    def test_public_proposal_cannot_apply_to_private_rfp(self):
        # Arrange
        self.assertEqual(
            self.grant.application_visibility, Grant.APPLICATION_VISIBILITY_OPTIONAL
        )
        proposal = self._own_proposal(is_public=True)
        self.client.force_authenticate(self.applicant)

        # Act
        resp = self.client.post(
            f"/api/grant/{self.grant.id}/application/?st={self.token}",
            {"preregistration_post_id": proposal.id},
        )

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(GrantApplication.objects.filter(grant=self.grant).exists())

    def test_creating_proposal_for_private_rfp_without_access_reports_not_found(self):
        # Arrange
        self.client.force_authenticate(self.applicant)
        posts_before = ResearchhubPost.objects.count()

        # Act
        resp = self.client.post(
            "/api/researchhubpost/",
            _proposal_body(grant_id=self.grant.id, is_public=False),
        )

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Grant not found", str(resp.data))
        self.assertEqual(ResearchhubPost.objects.count(), posts_before)

    def test_creating_proposal_with_token_defaults_to_private(self):
        # Arrange
        self.client.force_authenticate(self.applicant)

        # Act
        resp = self.client.post(
            f"/api/researchhubpost/?st={self.token}",
            _proposal_body(grant_id=self.grant.id),
        )

        # Assert
        self.assertEqual(resp.status_code, 200)
        post = ResearchhubPost.objects.get(id=resp.data["id"])
        self.assertFalse(post.unified_document.is_public)
        self.assertTrue(
            GrantApplication.objects.filter(
                grant=self.grant, preregistration_post=post
            ).exists()
        )

    def test_creating_public_proposal_for_private_rfp_is_rejected(self):
        # Arrange
        self.client.force_authenticate(self.applicant)

        # Act
        resp = self.client.post(
            f"/api/researchhubpost/?st={self.token}",
            _proposal_body(grant_id=self.grant.id, is_public=True),
        )

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(GrantApplication.objects.filter(grant=self.grant).exists())

    def test_proposal_applied_to_private_rfp_cannot_be_made_public(self):
        # Arrange
        proposal = self._own_proposal(is_public=False)
        GrantApplication.objects.create(
            grant=self.grant, preregistration_post=proposal, applicant=self.applicant
        )
        self.client.force_authenticate(self.applicant)

        # Act
        resp = self.client.post(f"/api/researchhubpost/{proposal.id}/make_public/")

        # Assert
        self.assertEqual(resp.status_code, 400)
        proposal.unified_document.refresh_from_db()
        self.assertFalse(proposal.unified_document.is_public)

    def test_private_rfp_cannot_require_public_applications(self):
        # Arrange
        author = create_random_default_user("priv_rfp_public_apps", moderator=True)
        make_user_verified(author)
        self.client.force_authenticate(author)
        grants_before = Grant.objects.count()

        # Act
        resp = self.client.post(
            "/api/researchhubpost/",
            _grant_post_body(
                is_public=False,
                grant_application_visibility=Grant.APPLICATION_VISIBILITY_PUBLIC,
            ),
        )

        # Assert
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Grant.objects.count(), grants_before)

    def test_grant_payload_exposes_effective_application_visibility(self):
        # Arrange
        self.client.force_authenticate(self.owner)

        # Act
        resp = self.client.get(f"/api/grant/{self.grant.id}/")

        # Assert
        self.assertEqual(
            resp.data["application_visibility"], Grant.APPLICATION_VISIBILITY_OPTIONAL
        )
        self.assertEqual(
            resp.data["effective_application_visibility"],
            Grant.APPLICATION_VISIBILITY_PRIVATE,
        )
