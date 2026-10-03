from decimal import Decimal

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from feed.cache_segment import (
    FEED_CACHE_SEGMENT_ADMIN,
    FEED_CACHE_SEGMENT_PUBLIC,
    get_feed_cache_segment,
    is_cache_disabled,
    is_cacheable_page,
)
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

    def _request(self, user=None, query=""):
        path = f"/api/funding_feed/{query}"
        drf_request = Request(self.factory.get(path))
        if user is None:
            drf_request.user = AnonymousUser()
        else:
            drf_request.user = user
        return drf_request

    def test_anonymous_returns_public_segment(self):
        # Act
        suffix = get_feed_cache_segment(self._request(), supports_private=True)

        # Assert
        self.assertEqual(suffix, FEED_CACHE_SEGMENT_PUBLIC)

    def test_activity_supports_private_false_always_public(self):
        # Arrange
        moderator = create_random_authenticated_user(
            "cache_seg_act_mod", moderator=True
        )

        # Act / Assert
        self.assertEqual(
            get_feed_cache_segment(self._request(moderator), supports_private=False),
            FEED_CACHE_SEGMENT_PUBLIC,
        )
        self.assertEqual(
            get_feed_cache_segment(self._request(), supports_private=False),
            FEED_CACHE_SEGMENT_PUBLIC,
        )

    def test_user_without_private_access_returns_public_segment(self):
        # Arrange
        user = create_random_authenticated_user("cache_seg_plain")

        # Act
        suffix = get_feed_cache_segment(self._request(user), supports_private=True)

        # Assert
        self.assertEqual(suffix, FEED_CACHE_SEGMENT_PUBLIC)

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
        suffix = get_feed_cache_segment(self._request(applicant), supports_private=True)

        # Assert
        self.assertEqual(suffix, f":viewer-{applicant.id}")

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
        suffix = get_feed_cache_segment(self._request(owner), supports_private=True)

        # Assert
        self.assertEqual(suffix, f":viewer-{owner.id}")

    def test_moderator_with_private_posts_uses_admin_segment(self):
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
        suffix = get_feed_cache_segment(self._request(moderator), supports_private=True)

        # Assert
        self.assertEqual(suffix, FEED_CACHE_SEGMENT_ADMIN)

    def test_hub_editor_uses_admin_segment(self):
        # Arrange
        from user.tests.helpers import create_hub_editor

        editor, _ = create_hub_editor("cache_seg_editor", "Cache Seg Hub")

        # Act
        suffix = get_feed_cache_segment(self._request(editor), supports_private=True)

        # Assert
        self.assertEqual(suffix, FEED_CACHE_SEGMENT_ADMIN)

    def test_moderator_grant_owner_uses_admin_segment(self):
        # Arrange
        moderator = create_random_authenticated_user(
            "cache_seg_mod_owner", moderator=True
        )
        applicant = create_random_authenticated_user("cache_seg_mod_app")
        grant_post = create_post(created_by=moderator, document_type=GRANT)
        Grant.objects.create(
            created_by=moderator,
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
        suffix = get_feed_cache_segment(self._request(moderator), supports_private=True)

        # Assert
        self.assertEqual(suffix, FEED_CACHE_SEGMENT_ADMIN)


class FeedCachePolicyHelpersTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    def _request(self, path="/api/funding_feed/", user=None, params=None):
        drf_request = Request(self.factory.get(path, params or {}))
        drf_request.user = user if user is not None else AnonymousUser()
        return drf_request

    def test_is_cache_disabled_requires_mod_and_param(self):
        # Arrange
        mod = create_random_authenticated_user("dis_cache_mod", moderator=True)
        plain = create_random_authenticated_user("dis_cache_plain")

        # Act / Assert
        self.assertFalse(is_cache_disabled(self._request()))
        self.assertFalse(
            is_cache_disabled(self._request(params={"disable_cache": "true"}))
        )
        self.assertFalse(
            is_cache_disabled(
                self._request(user=plain, params={"disable_cache": "true"})
            )
        )
        self.assertTrue(
            is_cache_disabled(self._request(user=mod, params={"disable_cache": "true"}))
        )
        self.assertTrue(
            is_cache_disabled(self._request(user=mod, params={"disable_cache": "1"}))
        )

    def test_is_cacheable_page_window(self):
        # Act / Assert
        self.assertTrue(is_cacheable_page(self._request(params={"page": "1"})))
        self.assertTrue(is_cacheable_page(self._request(params={"page": "20"})))
        self.assertFalse(is_cacheable_page(self._request(params={"page": "21"})))
        self.assertFalse(
            is_cacheable_page(
                self._request(params={"page": "1", "page_size": "40"}),
            )
        )
