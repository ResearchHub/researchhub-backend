import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from discussion.reaction_models import Vote as GrmVote
from hub.models import Hub
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

User = get_user_model()


class FundingFeedViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        self.hub = Hub.objects.create(
            name="Test Hub",
        )
        self.unified_document.hubs.add(self.hub)

        # Create a preregistration post
        self.post = ResearchhubPost.objects.create(
            title="Test Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="This is a test preregistration post",
            slug="test-preregistration",
            unified_document=self.unified_document,
            created_date=timezone.now(),
        )

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create another user and their content for testing
        self.other_user = User.objects.create_user(
            username="otheruser", password=uuid.uuid4().hex
        )
        self.other_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        self.other_hub = Hub.objects.create(name="Other Hub")
        self.other_unified_document.hubs.add(self.other_hub)

        # Create another preregistration post
        self.other_post = ResearchhubPost.objects.create(
            title="Other Preregistration",
            created_by=self.other_user,
            document_type=PREREGISTRATION,
            renderable_text="This is another test preregistration post",
            slug="other-preregistration",
            unified_document=self.other_unified_document,
            created_date=timezone.now(),
        )

        # Create a non-preregistration post (should not appear in feed)
        self.non_preregistration_document = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.non_preregistration_post = ResearchhubPost.objects.create(
            title="Discussion Post",
            created_by=self.user,
            document_type="DISCUSSION",
            renderable_text="This is a discussion post, not a preregistration",
            slug="discussion-post",
            unified_document=self.non_preregistration_document,
            created_date=timezone.now(),
        )

        # Create a removed document (should not appear in feed)
        self.removed_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION, is_removed=True
        )
        self.removed_post = ResearchhubPost.objects.create(
            title="Removed Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="This is a removed preregistration post",
            slug="removed-preregistration",
            unified_document=self.removed_document,
            created_date=timezone.now(),
        )

        cache.clear()

    def test_list_funding_feed(self):
        """Test that funding feed only returns preregistration posts"""
        url = reverse("funding_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only include non-removed preregistration posts (2 posts)
        self.assertEqual(len(response.data["results"]), 2)

        self.assertEqual(response.data["results"][0]["content_type"], "RESEARCHHUBPOST")

        post_ids = []
        for item in response.data["results"]:
            post_ids.append(item["content_object"]["id"])

        self.assertIn(self.post.id, post_ids)
        self.assertIn(self.other_post.id, post_ids)

        # Verify non-preregistration and removed posts are not included
        self.assertNotIn(self.non_preregistration_post.id, post_ids)
        self.assertNotIn(self.removed_post.id, post_ids)

    @patch("feed.views.funding_feed_view.cache")
    def test_funding_feed_cache(self, mock_cache):
        """Test caching functionality for funding feed"""
        # No cache on first request
        mock_cache.get.return_value = None

        url = reverse("funding_feed-list")
        response = self.client.get(url)

        self.assertTrue(mock_cache.get.called)
        self.assertTrue(mock_cache.set.called)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        # Return a "cached" response on second request
        mock_cache.get.return_value = mock_cache.set.call_args[0][1]
        mock_cache.set.reset_mock()

        response2 = self.client.get(url)

        self.assertTrue(mock_cache.get.called)
        self.assertFalse(mock_cache.set.called)

        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response2.data["results"]), 2)
        self.assertEqual(response.data["results"], response2.data["results"])

    def test_add_user_votes(self):
        """Test that user votes are added to response data"""
        # Create a vote for the post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        vote = GrmVote.objects.create(
            created_by=self.user,
            object_id=self.post.id,
            content_type=post_content_type,
            vote_type=GrmVote.UPVOTE,
        )

        url = reverse("funding_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Find the post in the response
        post_data = None
        for item in response.data["results"]:
            if item["content_object"]["id"] == self.post.id:
                post_data = item
                break

        self.assertIsNotNone(post_data)
        self.assertIn("user_vote", post_data)
        self.assertEqual(post_data["user_vote"]["id"], vote.id)

        # Use the integer value for the vote type, as that's what gets serialized
        vote_type = post_data["user_vote"]["vote_type"]
        self.assertEqual(vote_type, 1)  # 1 corresponds to UPVOTE

    @patch("feed.views.funding_feed_view.cache")
    def test_add_user_votes_with_cached_response(self, mock_cache):
        """Test that user votes are added even with cached response"""
        # Create a vote for the post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        vote = GrmVote.objects.create(
            created_by=self.user,
            object_id=self.post.id,
            content_type=post_content_type,
            vote_type=GrmVote.UPVOTE,
        )

        # Create a mock cached response without votes
        cached_response = {
            "results": [
                {
                    "id": self.post.id,
                    "content_type": "RESEARCHHUBPOST",
                    "content_object": {
                        "id": self.post.id,
                        "title": self.post.title,
                    },
                }
            ],
            "count": 1,
            "next": None,
            "previous": None,
        }
        mock_cache.get.return_value = cached_response

        url = reverse("funding_feed-list")
        response = self.client.get(url)

        # Check that votes were added to the cached response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIn("user_vote", response.data["results"][0])
        self.assertEqual(response.data["results"][0]["user_vote"]["id"], vote.id)

    def test_get_cache_key(self):
        """Test cache key generation logic"""
        from feed.views.funding_feed_view import FundingFeedViewSet

        # Create viewset instance and configure it
        viewset = FundingFeedViewSet()
        viewset.pagination_class = type(
            "MockPagination",
            (),
            {"page_size_query_param": "page_size", "page_size": 20},
        )

        # Test with anonymous user
        request_factory = APIRequestFactory()

        # Anonymous user
        request = request_factory.get("/api/funding_feed/")
        request = Request(request)

        # Use a mock user for the anonymous case
        anon_user = MagicMock()
        anon_user.is_authenticated = False
        anon_user.id = None
        request.user = anon_user

        cache_key = viewset._get_cache_key(request)
        self.assertEqual(cache_key, "funding_feed:anonymous:1-20")

        # Authenticated user
        request = request_factory.get("/api/funding_feed/")
        request = Request(request)

        # For authenticated user tests, create a mock that wraps the real user
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = self.user.id
        request.user = mock_user

        cache_key = viewset._get_cache_key(request)
        self.assertEqual(cache_key, f"funding_feed:{self.user.id}:1-20")

        # Custom page and page size
        request = request_factory.get("/api/funding_feed/?page=3&page_size=10")
        request = Request(request)
        request.user = mock_user

        cache_key = viewset._get_cache_key(request)
        self.assertEqual(cache_key, f"funding_feed:{self.user.id}:3-10")
