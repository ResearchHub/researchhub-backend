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
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import MORALIS
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
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

        # Create a preregistration post
        self.post = ResearchhubPost.objects.create(
            title="Test Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            renderable_text="This is a test preregistration post",
            slug="test-preregistration",
            unified_document=self.unified_document,
            created_date=timezone.now(),
            score=11,
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

        # Create an exchange rate for converting currency
        self.exchange_rate = RscExchangeRate.objects.create(
            price_source=MORALIS,
            rate=3.0,
            real_rate=3.0,
            target_currency=USD,
        )

        # Create fundraises for testing the fundraise_status filter
        # Create an open fundraise for the first post
        self.escrow1 = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.unified_document.id,
        )
        self.open_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=self.unified_document,
            escrow=self.escrow1,
            status=Fundraise.OPEN,
            goal_amount=100,
        )

        # Create a closed fundraise for the second post
        self.escrow2 = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.other_user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.other_unified_document.id,
        )
        self.closed_fundraise = Fundraise.objects.create(
            created_by=self.other_user,
            unified_document=self.other_unified_document,
            escrow=self.escrow2,
            status=Fundraise.CLOSED,
            goal_amount=100,
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

    def test_add_user_votes_and_metrics(self):
        """Test that user votes and metrics are added to response data"""
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
        self.assertEqual(post_data["user_vote"]["id"], vote.id)  # NOSONAR

        self.assertIn("metrics", post_data)
        self.assertEqual(post_data["metrics"]["votes"], 11)

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

        cache_key = viewset.get_cache_key(request, "funding")
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:1-20")

        # Authenticated user
        request = request_factory.get("/api/funding_feed/")
        request = Request(request)

        # For authenticated user tests, create a mock that wraps the real user
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = self.user.id
        request.user = mock_user

        cache_key = viewset.get_cache_key(request, "funding")
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:1-20")

        # Custom page and page size
        request = request_factory.get("/api/funding_feed/?page=3&page_size=10")
        request = Request(request)
        request.user = mock_user

        cache_key = viewset.get_cache_key(request, "funding")
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:3-10")

    def test_preregistration_post_only(self):
        """Test that funding feed only returns preregistration posts"""
        response = self.client.get(reverse("funding_feed-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        content_types = [result["content_type"] for result in results]

        # All returned items should be ResearchhubPost
        for content_type in content_types:
            self.assertEqual(content_type, "RESEARCHHUBPOST")

        # All returned items should be preregistration posts
        result_ids = [int(result["content_object"]["id"]) for result in results]
        for post_id in result_ids:
            post = ResearchhubPost.objects.get(id=post_id)
            self.assertEqual(post.document_type, PREREGISTRATION)

        # Discussion post should not be included
        self.assertNotIn(self.non_preregistration_post.id, result_ids)

    def test_fundraise_status_filter(self):
        """Test filtering feed by fundraise status"""
        # Test each filter option to ensure they can be passed without errors

        # Test filtering by OPEN status
        url = reverse("funding_feed-list") + "?fundraise_status=OPEN"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.post.id
        )

        # Test filtering by CLOSED status
        url = reverse("funding_feed-list") + "?fundraise_status=CLOSED"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.other_post.id
        )

    def test_open_fundraise_sorting(self):
        """Test that OPEN fundraises are sorted by end_date in ascending order"""
        # Create several additional open fundraises with different end dates

        # Create a unified document and post for each test fundraise
        # Earlier deadline (closest to now)
        early_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        early_post = ResearchhubPost.objects.create(
            title="Early Deadline Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=early_doc,
            created_date=timezone.now(),
        )

        # Medium deadline
        medium_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        medium_post = ResearchhubPost.objects.create(
            title="Medium Deadline Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=medium_doc,
            created_date=timezone.now(),
        )

        # Later deadline (furthest in future)
        later_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        later_post = ResearchhubPost.objects.create(
            title="Later Deadline Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=later_doc,
            created_date=timezone.now(),
        )

        # Create escrows for each fundraise
        escrow_early = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=early_doc.id,
        )

        escrow_medium = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=medium_doc.id,
        )

        escrow_later = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=later_doc.id,
        )

        # Create fundraises with different end dates (all OPEN)
        today = timezone.now()

        # Early deadline - 3 days from now
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=early_doc,
            escrow=escrow_early,
            status=Fundraise.OPEN,
            goal_amount=100,
            end_date=today + timezone.timedelta(days=3),
        )

        # Medium deadline - 10 days from now
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=medium_doc,
            escrow=escrow_medium,
            status=Fundraise.OPEN,
            goal_amount=100,
            end_date=today + timezone.timedelta(days=10),
        )

        # Later deadline - 30 days from now
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=later_doc,
            escrow=escrow_later,
            status=Fundraise.OPEN,
            goal_amount=100,
            end_date=today + timezone.timedelta(days=30),
        )

        # Query the OPEN fundraises
        url = reverse("funding_feed-list") + "?fundraise_status=OPEN"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have 4 results (the original open fundraise + 3 new ones)
        self.assertEqual(len(response.data["results"]), 4)

        # Extract post IDs in the order they are returned
        post_ids = [item["content_object"]["id"] for item in response.data["results"]]

        # Verify ordering - closest deadlines should be first
        # Check early_post is before medium_post
        self.assertLess(post_ids.index(early_post.id), post_ids.index(medium_post.id))

        # Check medium_post is before later_post
        self.assertLess(post_ids.index(medium_post.id), post_ids.index(later_post.id))

    def test_closed_fundraise_sorting(self):
        """Test that CLOSED fundraises are sorted by end_date in descending order"""
        # Create several additional closed fundraises with different end dates

        # Create unified documents and posts for test fundraises
        early_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        early_post = ResearchhubPost.objects.create(
            title="Early Closed Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=early_doc,
            created_date=timezone.now(),
        )

        medium_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        medium_post = ResearchhubPost.objects.create(
            title="Medium Closed Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=medium_doc,
            created_date=timezone.now(),
        )

        later_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        later_post = ResearchhubPost.objects.create(
            title="Later Closed Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=later_doc,
            created_date=timezone.now(),
        )

        # Create escrows for each fundraise
        escrow_early = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=early_doc.id,
        )

        escrow_medium = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=medium_doc.id,
        )

        escrow_later = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=later_doc.id,
        )

        # Create fundraises with different end dates (all CLOSED)
        today = timezone.now()

        # End dates in the past (all closed fundraises)
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=early_doc,
            escrow=escrow_early,
            status=Fundraise.CLOSED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=30),  # Oldest end date
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=medium_doc,
            escrow=escrow_medium,
            status=Fundraise.CLOSED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=10),  # Middle end date
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=later_doc,
            escrow=escrow_later,
            status=Fundraise.CLOSED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=3),  # Most recent end date
        )

        # Query the CLOSED fundraises
        url = reverse("funding_feed-list") + "?fundraise_status=CLOSED"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have 4 results (the original closed fundraise + 3 new ones)
        self.assertEqual(len(response.data["results"]), 4)

        # Extract post IDs in the order they are returned
        post_ids = [item["content_object"]["id"] for item in response.data["results"]]

        # Verify ordering - most recent end dates should be first for CLOSED
        # Check later_post (most recent end date) is before medium_post
        self.assertLess(post_ids.index(later_post.id), post_ids.index(medium_post.id))

        # Check medium_post is before early_post
        self.assertLess(post_ids.index(medium_post.id), post_ids.index(early_post.id))

    def test_all_fundraise_conditional_sorting(self):
        """Test the conditional sorting for the ALL tab (mixed OPEN and CLOSED fundraises)"""
        # Create an additional open fundraise with early deadline
        early_open_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        early_open_post = ResearchhubPost.objects.create(
            title="Early Open Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=early_open_doc,
            created_date=timezone.now(),
        )

        escrow_early_open = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=early_open_doc.id,
        )

        today = timezone.now()
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=early_open_doc,
            escrow=escrow_early_open,
            status=Fundraise.OPEN,
            goal_amount=100,
            end_date=today + timezone.timedelta(days=3),  # Very close deadline
        )

        # Create an additional open fundraise with later deadline
        later_open_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        later_open_post = ResearchhubPost.objects.create(
            title="Later Open Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=later_open_doc,
            created_date=timezone.now(),
        )

        escrow_later_open = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=later_open_doc.id,
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=later_open_doc,
            escrow=escrow_later_open,
            status=Fundraise.OPEN,
            goal_amount=100,
            end_date=today + timezone.timedelta(days=30),  # Further deadline
        )

        # Create an additional closed fundraise with recent end date
        recent_closed_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        recent_closed_post = ResearchhubPost.objects.create(
            title="Recent Closed Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=recent_closed_doc,
            created_date=timezone.now(),
        )

        escrow_recent_closed = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=recent_closed_doc.id,
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=recent_closed_doc,
            escrow=escrow_recent_closed,
            status=Fundraise.CLOSED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=3),  # Recently closed
        )

        # Create an additional closed fundraise with older end date
        old_closed_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        old_closed_post = ResearchhubPost.objects.create(
            title="Old Closed Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=old_closed_doc,
            created_date=timezone.now(),
        )

        escrow_old_closed = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=old_closed_doc.id,
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=old_closed_doc,
            escrow=escrow_old_closed,
            status=Fundraise.CLOSED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=30),  # Closed a while ago
        )

        # Query the ALL fundraises (no filter)
        url = reverse("funding_feed-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have 6 results (2 original + 4 new ones)
        self.assertEqual(len(response.data["results"]), 6)

        # Extract post IDs in the order they are returned
        post_ids = [item["content_object"]["id"] for item in response.data["results"]]

        # Verify the ordering is as expected:
        # 1. All OPEN fundraises should come before CLOSED ones
        # 2. Within OPEN, closer deadlines should be first
        # 3. Within CLOSED, more recent end dates should be first

        # All open posts should come before all closed posts
        all_open_post_ids = [early_open_post.id, later_open_post.id, self.post.id]
        all_closed_post_ids = [
            recent_closed_post.id,
            old_closed_post.id,
            self.other_post.id,
        ]

        # Get the last index of any open post
        last_open_index = max(post_ids.index(post_id) for post_id in all_open_post_ids)

        # Get the first index of any closed post
        first_closed_index = min(
            post_ids.index(post_id) for post_id in all_closed_post_ids
        )

        # Verify that all open posts come before all closed posts
        self.assertLess(last_open_index, first_closed_index)

        # Within OPEN posts, verify closer deadlines come first
        self.assertLess(
            post_ids.index(early_open_post.id), post_ids.index(later_open_post.id)
        )

        # Within CLOSED posts, verify more recent end dates come first
        self.assertLess(
            post_ids.index(recent_closed_post.id), post_ids.index(old_closed_post.id)
        )
