from datetime import timedelta
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from purchase.models import Grant, GrantApplication
from research_ai.models import ExpertSearch, GeneratedEmail
from research_ai.services.invited_experts_service import (
    grant_invited_expert_access_for_signup,
)
from researchhub_access_group.constants import VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import GRANT
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.tests.helpers import (
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
        self.hub = create_hub()

    def test_grant_defaults_to_public(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/api/researchhubpost/",
            _grant_post_body(hubs=[self.hub.id]),
        )
        self.assertEqual(resp.status_code, 200)
        post_id = resp.data["id"]
        post = ResearchhubPost.objects.get(id=post_id)
        self.assertTrue(post.unified_document.is_public)

    def test_grant_can_be_created_private(self):
        self.client.force_authenticate(self.author)
        resp = self.client.post(
            "/api/researchhubpost/",
            _grant_post_body(is_public=False, hubs=[self.hub.id]),
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

    def test_grant_feed_hides_private_from_owner(self):
        """Private grants are excluded from the feed for everyone, including
        the owner. The owner accesses them via the direct post/grant URL."""
        self.client.force_authenticate(self.owner)
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertNotIn("Private Grant", titles)

    def test_grant_feed_hides_private_from_permitted_user(self):
        """Permission rows grant detail-page access but do not surface private
        grants in the shared feed (which is cached across all users)."""
        self.client.force_authenticate(self.invitee)
        resp = self.client.get("/api/grant_feed/")
        self.assertEqual(resp.status_code, 200)
        titles = [r["content_object"]["title"] for r in resp.data["results"]]
        self.assertIn("Public Grant", titles)
        self.assertNotIn("Private Grant", titles)

    def test_grant_viewset_hides_private_from_unrelated_user(self):
        self.client.force_authenticate(self.other)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 404)

    def test_grant_viewset_shows_private_to_owner(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)

    def test_grant_viewset_shows_private_to_permitted_user(self):
        self.client.force_authenticate(self.invitee)
        resp = self.client.get(f"/api/grant/{self.private_grant.id}/")
        self.assertEqual(resp.status_code, 200)


class InviteAccessGrantForPrivateGrantTests(APITestCase):
    """grant_invited_expert_access_for_signup must now create a Permission on
    a private GRANT (previously only on PREREGISTRATIONs)."""

    def setUp(self):
        cache.clear()
        self.owner = create_random_authenticated_user("invite_owner")
        self.invitee_email = "applicant@example.com"

        post = create_post(created_by=self.owner, document_type=GRANT)
        post.unified_document.is_public = False
        post.unified_document.save(update_fields=["is_public"])
        Grant.objects.create(
            created_by=self.owner,
            unified_document=post.unified_document,
            amount=Decimal("30000.00"),
            currency="USD",
            organization="OrgX",
            description="d",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

        search = ExpertSearch.objects.create(
            created_by=self.owner,
            unified_document=post.unified_document,
            name="RFP Applicant Invites",
            query="x",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.COMPLETED,
            progress=100,
        )
        GeneratedEmail.objects.create(
            created_by=self.owner,
            expert_search=search,
            expert_email=self.invitee_email,
            email_subject="s",
            email_body="b",
            status=GeneratedEmail.Status.SENT,
        )
        self.unified_doc = post.unified_document

    def test_signup_grants_viewer_permission_on_private_grant(self):
        new_user = create_random_authenticated_user("late_signup")
        # Move signup into the window relative to the invite's created_date.
        new_user.email = self.invitee_email
        new_user.date_joined = timezone.now()
        new_user.save(update_fields=["email", "date_joined"])

        granted = grant_invited_expert_access_for_signup(
            normalized_email=self.invitee_email, user=new_user
        )
        self.assertEqual(granted, 1)

        ud_ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        self.assertTrue(
            Permission.objects.filter(
                content_type=ud_ct,
                object_id=self.unified_doc.id,
                user=new_user,
                access_type=VIEWER,
            ).exists()
        )
