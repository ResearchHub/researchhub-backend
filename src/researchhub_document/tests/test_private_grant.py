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
