from decimal import Decimal

from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.cache_segment import get_feed_cache_segment
from purchase.models import Grant, GrantApplication
from purchase.related_models.constants.currency import USD
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import (
    create_random_authenticated_user,
)
from utils.test_helpers import AWSMockTestCase


class FeedCacheSegmentTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def _request(self, user=None):
        drf_request = Request(self.factory.get("/api/funding_feed/"))
        if user is None:
            from django.contrib.auth.models import AnonymousUser

            drf_request.user = AnonymousUser()
        else:
            drf_request.user = user
        return drf_request

    def test_anonymous_returns_public_segment(self):
        # Act
        suffix, should_cache = get_feed_cache_segment(self._request())

        # Assert
        self.assertEqual(suffix, ":public")
        self.assertTrue(should_cache)

    def test_user_without_private_access_returns_public_segment(self):
        # Arrange
        user = create_random_authenticated_user("cache_seg_plain")

        # Act
        suffix, should_cache = get_feed_cache_segment(self._request(user))

        # Assert
        self.assertEqual(suffix, ":public")
        self.assertTrue(should_cache)

    def test_applicant_with_private_prereg_returns_viewer_segment(self):
        # Arrange
        applicant = create_random_authenticated_user("cache_seg_applicant")
        private_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION, is_public=False
        )
        ResearchhubPost.objects.create(
            title="Private Preregistration",
            created_by=applicant,
            document_type=PREREGISTRATION,
            renderable_text="Private proposal",
            slug="private-prereg-cache-seg",
            unified_document=private_doc,
            created_date=timezone.now(),
        )

        # Act
        suffix, should_cache = get_feed_cache_segment(self._request(applicant))

        # Assert
        self.assertEqual(suffix, f":viewer-{applicant.id}")
        self.assertTrue(should_cache)

    def test_grant_owner_with_private_application_returns_viewer_segment(self):
        # Arrange
        owner = create_random_authenticated_user("cache_seg_owner")
        applicant = create_random_authenticated_user("cache_seg_app")
        grant_post = create_post(created_by=owner, document_type=GRANT)
        Grant.objects.create(
            created_by=owner,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency=USD,
            organization="Org",
            description="desc",
        )
        private_post = create_post(
            created_by=applicant, document_type=PREREGISTRATION, title="Private"
        )
        private_post.unified_document.is_public = False
        private_post.unified_document.save()
        GrantApplication.objects.create(
            grant=Grant.objects.get(unified_document=grant_post.unified_document),
            preregistration_post=private_post,
            applicant=applicant,
        )

        # Act
        suffix, should_cache = get_feed_cache_segment(self._request(owner))

        # Assert
        self.assertEqual(suffix, f":viewer-{owner.id}")
        self.assertTrue(should_cache)

    def test_moderator_disables_caching_even_with_private_posts(self):
        # Arrange
        moderator = create_random_authenticated_user("cache_seg_mod", moderator=True)
        private_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION, is_public=False
        )
        ResearchhubPost.objects.create(
            title="Private Preregistration",
            created_by=moderator,
            document_type=PREREGISTRATION,
            renderable_text="Private proposal",
            slug="private-prereg-mod-cache-seg",
            unified_document=private_doc,
            created_date=timezone.now(),
        )

        # Act
        suffix, should_cache = get_feed_cache_segment(self._request(moderator))

        # Assert
        self.assertIsNone(suffix)
        self.assertFalse(should_cache)
