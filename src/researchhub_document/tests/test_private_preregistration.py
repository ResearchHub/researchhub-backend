import uuid

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from hub.models import Hub
from purchase.related_models.constants.currency import USD
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import (
    ResearchhubPost,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import make_user_verified
from utils.test_helpers import AWSMockTestCase

User = get_user_model()

LONG_TITLE = "sufficiently long title. sufficiently long title."
LONG_BODY = (
    "sufficiently long body. sufficiently long body. "
    "sufficiently long body. sufficiently long body. "
    "sufficiently long body."
)


def _make_user(name):
    user = User.objects.create_user(
        username=f"{name}-{uuid.uuid4().hex[:8]}",
        password=uuid.uuid4().hex,
    )
    make_user_verified(user)
    return user


class PrivatePreregistrationCreateTests(AWSMockTestCase):
    """Posting `is_public=False` makes the unified document private."""

    def setUp(self):
        super().setUp()
        self.author = _make_user("author")
        self.hub = Hub.objects.create(name=f"hub-{uuid.uuid4().hex[:8]}")
        RscExchangeRate.objects.create(rate=1.0)
        self.client = APIClient()
        self.client.force_authenticate(self.author)

    def _payload(self, **overrides):
        payload = {
            "document_type": PREREGISTRATION,
            "created_by": self.author.id,
            "full_src": "body",
            "renderable_text": LONG_BODY,
            "title": LONG_TITLE,
            "hubs": [self.hub.id],
            "fundraise_goal_amount": 1000,
        }
        payload.update(overrides)
        return payload

    def test_default_post_is_public(self):
        response = self.client.post(
            "/api/researchhubpost/", self._payload(), format="json"
        )

        self.assertEqual(response.status_code, 200)
        post = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertTrue(post.unified_document.is_public)

    def test_is_public_false_marks_unified_doc_private(self):
        response = self.client.post(
            "/api/researchhubpost/",
            self._payload(is_public=False),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        post = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertFalse(post.unified_document.is_public)

    def test_is_public_false_ignored_for_non_preregistration(self):
        response = self.client.post(
            "/api/researchhubpost/",
            self._payload(
                document_type="DISCUSSION",
                is_public=False,
                fundraise_goal_amount=None,
            ),
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        post = ResearchhubPost.objects.get(id=response.data["id"])
        self.assertTrue(post.unified_document.is_public)


class VisibleToQuerySetTests(AWSMockTestCase):
    """ResearchhubPost.objects.visible_to filters by is_public + permissions."""

    def setUp(self):
        super().setUp()
        self.author = _make_user("author")
        self.outsider = _make_user("outsider")
        self.grant_owner = _make_user("grant_owner")

        self.public_post = create_post(
            title="Public post", created_by=self.author, document_type=PREREGISTRATION
        )
        self.private_post = create_post(
            title="Private post",
            created_by=self.author,
            document_type=PREREGISTRATION,
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save()

        # Grant owned by `grant_owner`; the private post applies to it.
        self.grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )
        self.grant = Grant.objects.create(
            created_by=self.grant_owner,
            unified_document=self.grant_doc,
            amount=1000,
            currency=USD,
            organization="Org",
            description="desc",
        )
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.private_post,
            applicant=self.author,
        )

    def test_anonymous_only_sees_public(self):
        ids = set(ResearchhubPost.objects.visible_to(None).values_list("id", flat=True))
        self.assertIn(self.public_post.id, ids)
        self.assertNotIn(self.private_post.id, ids)

    def test_outsider_only_sees_public(self):
        ids = set(
            ResearchhubPost.objects.visible_to(self.outsider).values_list(
                "id", flat=True
            )
        )
        self.assertIn(self.public_post.id, ids)
        self.assertNotIn(self.private_post.id, ids)

    def test_author_sees_own_private(self):
        ids = set(
            ResearchhubPost.objects.visible_to(self.author).values_list("id", flat=True)
        )
        self.assertIn(self.public_post.id, ids)
        self.assertIn(self.private_post.id, ids)

    def test_grant_owner_sees_application_private(self):
        ids = set(
            ResearchhubPost.objects.visible_to(self.grant_owner).values_list(
                "id", flat=True
            )
        )
        self.assertIn(self.private_post.id, ids)


class PostViewSetVisibilityTests(AWSMockTestCase):
    """ResearchhubPostViewSet hides private posts from non-authorized requesters."""

    def setUp(self):
        super().setUp()
        self.author = _make_user("author")
        self.outsider = _make_user("outsider")
        self.grant_owner = _make_user("grant_owner")

        self.private_post = create_post(
            title="Private", created_by=self.author, document_type=PREREGISTRATION
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save()

        self.grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )
        self.grant = Grant.objects.create(
            created_by=self.grant_owner,
            unified_document=self.grant_doc,
            amount=1000,
            currency=USD,
            organization="Org",
            description="desc",
        )
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.private_post,
            applicant=self.author,
        )

    def test_outsider_cannot_retrieve_private_post(self):
        client = APIClient()
        client.force_authenticate(self.outsider)
        response = client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_anonymous_cannot_retrieve_private_post(self):
        client = APIClient()
        response = client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_author_can_retrieve_private_post(self):
        client = APIClient()
        client.force_authenticate(self.author)
        response = client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_grant_owner_can_retrieve_private_post(self):
        client = APIClient()
        client.force_authenticate(self.grant_owner)
        response = client.get(f"/api/researchhubpost/{self.private_post.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class FundingFeedPrivacyTests(AWSMockTestCase):
    """Funding feed excludes private posts unless the requester can see them."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.author = _make_user("author")
        self.outsider = _make_user("outsider")
        self.grant_owner = _make_user("grant_owner")

        self.public_post = create_post(
            title="Public", created_by=self.author, document_type=PREREGISTRATION
        )
        self.private_post = create_post(
            title="Private", created_by=self.author, document_type=PREREGISTRATION
        )
        self.private_post.unified_document.is_public = False
        self.private_post.unified_document.save()

        self.grant_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="GRANT"
        )
        self.grant = Grant.objects.create(
            created_by=self.grant_owner,
            unified_document=self.grant_doc,
            amount=1000,
            currency=USD,
            organization="Org",
            description="desc",
        )
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.private_post,
            applicant=self.author,
        )

    def _ids(self, response):
        return {item["content_object"]["id"] for item in response.data["results"]}

    def test_anonymous_does_not_see_private(self):
        client = APIClient()
        response = client.get(reverse("funding_feed-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = self._ids(response)
        self.assertIn(self.public_post.id, ids)
        self.assertNotIn(self.private_post.id, ids)

    def test_outsider_does_not_see_private(self):
        client = APIClient()
        client.force_authenticate(self.outsider)
        response = client.get(reverse("funding_feed-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn(self.private_post.id, self._ids(response))

    def test_author_sees_own_private(self):
        client = APIClient()
        client.force_authenticate(self.author)
        response = client.get(reverse("funding_feed-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.private_post.id, self._ids(response))

    def test_grant_owner_sees_application_private(self):
        client = APIClient()
        client.force_authenticate(self.grant_owner)
        response = client.get(reverse("funding_feed-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(self.private_post.id, self._ids(response))
