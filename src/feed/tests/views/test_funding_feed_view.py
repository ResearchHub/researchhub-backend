import uuid
from unittest.mock import MagicMock, patch
from urllib.parse import quote

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.request import Request
from rest_framework.test import APIClient, APIRequestFactory

from discussion.models import Vote
from hub.models import Hub
from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import MORALIS
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from review.models.review_model import Review
from user.related_models.user_verification_model import UserVerification

User = get_user_model()

RSC_TO_USD_RATE = 3.0


class FundingFeedViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )
        UserVerification.objects.create(
            user=self.user, status=UserVerification.Status.APPROVED
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
            score=5,
        )

        # Create reviews for both documents from the alternate users
        self.review = Review.objects.create(
            score=4.0,
            created_by=self.other_user,
            unified_document=self.unified_document,
            created_date=timezone.now(),
        )
        self.other_review = Review.objects.create(
            score=2.0,
            created_by=self.user,
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
            rate=RSC_TO_USD_RATE,
            real_rate=RSC_TO_USD_RATE,
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

        # Create a nonprofit for the fundraise link
        self.nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit",
            ein="123456789",
            endaoment_org_id="test-org-id",
        )
        self.link = NonprofitFundraiseLink.objects.create(
            nonprofit=self.nonprofit,
            fundraise=self.open_fundraise,
            note="Test note for this link",
        )

        # Create a completed fundraise for the second post
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
            status=Fundraise.COMPLETED,
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
        vote = Vote.objects.create(
            created_by=self.user,
            object_id=self.post.id,
            content_type=post_content_type,
            vote_type=Vote.UPVOTE,
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
        vote = Vote.objects.create(
            created_by=self.user,
            object_id=self.post.id,
            content_type=post_content_type,
            vote_type=Vote.UPVOTE,
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
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:1-20:all")

        # Authenticated user
        request = request_factory.get("/api/funding_feed/")
        request = Request(request)

        # For authenticated user tests, create a mock that wraps the real user
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.id = self.user.id
        request.user = mock_user

        cache_key = viewset.get_cache_key(request, "funding")
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:1-20:all")

        # Custom page and page size
        request = request_factory.get("/api/funding_feed/?page=3&page_size=10")
        request = Request(request)
        request.user = mock_user

        cache_key = viewset.get_cache_key(request, "funding")
        self.assertEqual(cache_key, "funding_feed:latest:all:all:none:3-10:all")

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

        # Create fundraises with different end dates (all COMPLETED)
        today = timezone.now()

        # End dates in the past (all completed fundraises)
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=early_doc,
            escrow=escrow_early,
            status=Fundraise.COMPLETED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=30),  # Oldest end date
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=medium_doc,
            escrow=escrow_medium,
            status=Fundraise.COMPLETED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=10),  # Middle end date
        )

        Fundraise.objects.create(
            created_by=self.user,
            unified_document=later_doc,
            escrow=escrow_later,
            status=Fundraise.COMPLETED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=3),  # Most recent end date
        )

        # Query the CLOSED fundraises
        url = reverse("funding_feed-list") + "?fundraise_status=CLOSED"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have 4 results (the original completed fundraise + 3 new ones)
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

        # Create an additional completed fundraise with recent end date
        recent_closed_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        recent_closed_post = ResearchhubPost.objects.create(
            title="Recent Completed Post",
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
            status=Fundraise.COMPLETED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=3),  # Recently completed
        )

        # Create an additional completed fundraise with older end date
        old_closed_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        old_closed_post = ResearchhubPost.objects.create(
            title="Old Completed Post",
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
            status=Fundraise.COMPLETED,
            goal_amount=100,
            end_date=today - timezone.timedelta(days=30),  # Completed a while ago
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
        # 1. All OPEN fundraises should come before COMPLETED ones
        # 2. Within OPEN, closer deadlines should be first
        # 3. Within COMPLETED, more recent end dates should be first

        # All open posts should come before all completed posts
        all_open_post_ids = [early_open_post.id, later_open_post.id, self.post.id]
        all_completed_post_ids = [
            recent_closed_post.id,
            old_closed_post.id,
            self.other_post.id,
        ]

        # Get the last index of any open post
        last_open_index = max(post_ids.index(post_id) for post_id in all_open_post_ids)

        # Get the first index of any completed post
        first_completed_index = min(
            post_ids.index(post_id) for post_id in all_completed_post_ids
        )

        # Verify that all open posts come before all completed posts
        self.assertLess(last_open_index, first_completed_index)

        # Within OPEN posts, verify closer deadlines come first
        self.assertLess(
            post_ids.index(early_open_post.id), post_ids.index(later_open_post.id)
        )

        # Within COMPLETED posts, verify more recent end dates come first
        self.assertLess(
            post_ids.index(recent_closed_post.id), post_ids.index(old_closed_post.id)
        )

    def test_grant_id_filter(self):
        """Test filtering funding feed by grant_id parameter"""
        # Create a grant and grant unified document
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        ResearchhubPost.objects.create(
            title="Test Grant",
            created_by=self.user,
            document_type=GRANT,
            unified_document=grant_doc,
            created_date=timezone.now(),
        )

        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=50000.00,
            currency="USD",
            organization="Test Foundation",
            description="Test grant description",
            status=Grant.OPEN,
        )

        # Create a grant application linking the grant to our preregistration post
        GrantApplication.objects.create(
            grant=grant, preregistration_post=self.post, applicant=self.user
        )

        # Create another preregistration post without grant application
        other_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Other Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=other_doc,
            created_date=timezone.now(),
        )

        # Test filtering by grant_id
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

        # Should only return the post that applied to this grant
        returned_post_id = response.data["results"][0]["content_object"]["id"]
        self.assertEqual(returned_post_id, self.post.id)

    def test_grant_id_filter_no_applications(self):
        """Test grant_id filter when grant has no applications"""
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=25000.00,
            currency="USD",
            organization="Empty Grant Foundation",
            description="Grant with no applications",
            status=Grant.OPEN,
        )

        # Filter by grant that has no applications
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_grant_id_filter_with_ordering_newest(self):
        """Test grant_id filter with ordering by newest"""
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=30000.00,
            currency="USD",
            organization="Test Foundation",
            description="Test grant",
            status=Grant.OPEN,
        )

        # Create multiple preregistration posts with different creation dates
        older_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        older_post = ResearchhubPost.objects.create(
            title="Older Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=older_doc,
            created_date=timezone.now() - timezone.timedelta(days=2),
        )

        newer_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        newer_post = ResearchhubPost.objects.create(
            title="Newer Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=newer_doc,
            created_date=timezone.now() - timezone.timedelta(days=1),
        )

        # Create grant applications for both posts
        GrantApplication.objects.create(
            grant=grant, preregistration_post=older_post, applicant=self.user
        )
        GrantApplication.objects.create(
            grant=grant, preregistration_post=newer_post, applicant=self.user
        )

        # Test ordering by newest (default)
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}&ordering=newest"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        # Newer post should come first
        first_post_id = response.data["results"][0]["content_object"]["id"]
        second_post_id = response.data["results"][1]["content_object"]["id"]

        self.assertEqual(first_post_id, newer_post.id)
        self.assertEqual(second_post_id, older_post.id)

    def test_grant_id_filter_with_ordering_hot_score(self):
        """Test grant_id filter with ordering by hot_score"""
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=40000.00,
            currency="USD",
            organization="Hot Score Foundation",
            description="Test grant for hot score ordering",
            status=Grant.OPEN,
        )

        # Create preregistration posts with different hot scores
        low_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION, hot_score=10.0
        )
        low_score_post = ResearchhubPost.objects.create(
            title="Low Score Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=low_score_doc,
            created_date=timezone.now(),
        )

        high_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION, hot_score=100.0
        )
        high_score_post = ResearchhubPost.objects.create(
            title="High Score Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_score_doc,
            created_date=timezone.now(),
        )

        # Create grant applications for both posts
        GrantApplication.objects.create(
            grant=grant, preregistration_post=low_score_post, applicant=self.user
        )
        GrantApplication.objects.create(
            grant=grant, preregistration_post=high_score_post, applicant=self.user
        )

        # Test ordering by hot_score
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}&ordering=hot_score"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        # High score post should come first
        first_post_id = response.data["results"][0]["content_object"]["id"]
        second_post_id = response.data["results"][1]["content_object"]["id"]

        self.assertEqual(first_post_id, high_score_post.id)
        self.assertEqual(second_post_id, low_score_post.id)

    def test_grant_id_filter_with_ordering_upvotes(self):
        """Test grant_id filter with ordering by upvotes (score)"""
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=35000.00,
            currency="USD",
            organization="Upvote Foundation",
            description="Test grant for upvote ordering",
            status=Grant.OPEN,
        )

        # Create preregistration posts with different scores
        low_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        low_score_post = ResearchhubPost.objects.create(
            title="Low Upvote Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=low_score_doc,
            created_date=timezone.now(),
            score=5,
        )

        high_score_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        high_score_post = ResearchhubPost.objects.create(
            title="High Upvote Preregistration",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_score_doc,
            created_date=timezone.now(),
            score=50,
        )

        # Create grant applications for both posts
        GrantApplication.objects.create(
            grant=grant, preregistration_post=low_score_post, applicant=self.user
        )
        GrantApplication.objects.create(
            grant=grant, preregistration_post=high_score_post, applicant=self.user
        )

        # Test ordering by upvotes
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}&ordering=upvotes"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        # High score post should come first
        first_post_id = response.data["results"][0]["content_object"]["id"]
        second_post_id = response.data["results"][1]["content_object"]["id"]

        self.assertEqual(first_post_id, high_score_post.id)
        self.assertEqual(second_post_id, low_score_post.id)

    def test_grant_id_filter_with_ordering_amount_raised(self):
        """Test grant_id filter with ordering by amount_raised"""

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=50000.00,
            currency="USD",
            organization="Amount Raised Foundation",
            description="Test grant for amount_raised ordering",
            status=Grant.OPEN,
        )

        # Create posts with different amounts raised
        # High amount
        high_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        high_post = ResearchhubPost.objects.create(
            title="High Amount Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_doc,
        )
        high_escrow = Escrow.objects.create(
            amount_holding=1000,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=high_doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=high_doc,
            escrow=high_escrow,
            status=Fundraise.OPEN,
        )

        # Low amount
        low_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        low_post = ResearchhubPost.objects.create(
            title="Low Amount Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=low_doc,
        )
        low_escrow = Escrow.objects.create(
            amount_holding=100,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=low_doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=low_doc,
            escrow=low_escrow,
            status=Fundraise.OPEN,
        )

        # Another post not associated with the grant
        unrelated_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Unrelated Amount Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=unrelated_doc,
        )
        unrelated_escrow = Escrow.objects.create(
            amount_holding=5000,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=unrelated_doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=unrelated_doc,
            escrow=unrelated_escrow,
            status=Fundraise.OPEN,
        )

        # Create grant applications for both posts
        GrantApplication.objects.create(
            grant=grant, preregistration_post=low_post, applicant=self.user
        )
        GrantApplication.objects.create(
            grant=grant, preregistration_post=high_post, applicant=self.user
        )

        # Test ordering by amount_raised
        url = (
            reverse("funding_feed-list")
            + f"?grant_id={grant.id}&ordering=amount_raised"
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)

        # High amount post should come first
        first_post_id = response.data["results"][0]["content_object"]["id"]
        second_post_id = response.data["results"][1]["content_object"]["id"]

        self.assertEqual(first_post_id, high_post.id)
        self.assertEqual(second_post_id, low_post.id)

    def test_grant_id_filter_disables_caching(self):
        """Test that grant_id filter disables caching"""
        from researchhub_document.related_models.constants.document_type import GRANT

        grant_doc = ResearchhubUnifiedDocument.objects.create(document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_doc,
            amount=20000.00,
            currency="USD",
            organization="Cache Test Foundation",
            description="Test grant for cache behavior",
            status=Grant.OPEN,
        )

        GrantApplication.objects.create(
            grant=grant, preregistration_post=self.post, applicant=self.user
        )

        # Clear cache before test
        cache.clear()

        # Make request with grant_id filter
        url = reverse("funding_feed-list") + f"?grant_id={grant.id}&page=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify that cache was not used for this request
        # The view should not cache responses when grant_id is provided
        cache_key = "funding_feed:latest:all:all:none:1-20:all"
        cached_response = cache.get(cache_key)

        # Cache should be None since grant_id disables caching
        self.assertIsNone(cached_response)

    def test_grant_id_filter_invalid_grant_id(self):
        """Test grant_id filter with invalid grant ID"""
        # Use a non-existent grant ID
        url = reverse("funding_feed-list") + "?grant_id=99999"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 0)

    def test_created_by_filter(self):
        """Test filtering funding feed by created_by parameter"""
        # Create a third user and their preregistration post
        third_user = User.objects.create_user(
            username="thirduser", password=uuid.uuid4().hex
        )
        third_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        third_post = ResearchhubPost.objects.create(
            title="Third User Preregistration",
            created_by=third_user,
            document_type=PREREGISTRATION,
            renderable_text="Post by third user",
            slug="third-user-preregistration",
            unified_document=third_doc,
            created_date=timezone.now(),
        )

        # Test filtering by first user's ID
        url = reverse("funding_feed-list") + f"?created_by={self.user.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return posts created by self.user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.post.id
        )

        # Test filtering by other_user's ID
        url = reverse("funding_feed-list") + f"?created_by={self.other_user.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return posts created by other_user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.other_post.id
        )

        # Test filtering by third_user's ID
        url = reverse("funding_feed-list") + f"?created_by={third_user.id}"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return posts created by third_user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], third_post.id
        )

    def test_created_by_filter_disables_caching(self):
        """Test that created_by filter disables caching"""
        # Clear cache before test
        cache.clear()

        # Make request with created_by filter
        url = reverse("funding_feed-list") + f"?created_by={self.user.id}&page=1"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify that cache was not used for this request
        # The view should not cache responses when created_by is provided
        cache_key = "funding_feed:latest:all:all:none:1-20:all"
        cached_response = cache.get(cache_key)

        # Cache should be None since created_by disables caching
        self.assertIsNone(cached_response)

    def test_created_by_filter_with_fundraise_status(self):
        """Test created_by filter combined with fundraise_status filter"""
        # Create another user with posts and fundraises
        fourth_user = User.objects.create_user(
            username="fourthuser", password=uuid.uuid4().hex
        )

        # Create an open fundraise post for fourth_user
        fourth_doc_open = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fourth_post_open = ResearchhubPost.objects.create(
            title="Fourth User Open Fundraise",
            created_by=fourth_user,
            document_type=PREREGISTRATION,
            renderable_text="Open fundraise by fourth user",
            slug="fourth-user-open-fundraise",
            unified_document=fourth_doc_open,
            created_date=timezone.now(),
        )

        escrow_fourth_open = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=fourth_user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=fourth_doc_open.id,
        )
        Fundraise.objects.create(
            created_by=fourth_user,
            unified_document=fourth_doc_open,
            escrow=escrow_fourth_open,
            status=Fundraise.OPEN,
            goal_amount=100,
        )

        # Create a closed fundraise post for fourth_user
        fourth_doc_closed = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        fourth_post_closed = ResearchhubPost.objects.create(
            title="Fourth User Closed Fundraise",
            created_by=fourth_user,
            document_type=PREREGISTRATION,
            renderable_text="Closed fundraise by fourth user",
            slug="fourth-user-closed-fundraise",
            unified_document=fourth_doc_closed,
            created_date=timezone.now(),
        )

        escrow_fourth_closed = Escrow.objects.create(
            amount_holding=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=fourth_user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=fourth_doc_closed.id,
        )
        Fundraise.objects.create(
            created_by=fourth_user,
            unified_document=fourth_doc_closed,
            escrow=escrow_fourth_closed,
            status=Fundraise.COMPLETED,
            goal_amount=100,
        )

        # Test created_by + OPEN fundraise_status
        url = (
            reverse("funding_feed-list")
            + f"?created_by={fourth_user.id}&fundraise_status=OPEN"
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return OPEN fundraises created by fourth_user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], fourth_post_open.id
        )

        # Test created_by + CLOSED fundraise_status
        url = (
            reverse("funding_feed-list")
            + f"?created_by={fourth_user.id}&fundraise_status=CLOSED"
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return CLOSED fundraises created by fourth_user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], fourth_post_closed.id
        )

        # Test created_by filter for different user
        url = (
            reverse("funding_feed-list")
            + f"?created_by={self.user.id}&fundraise_status=OPEN"
        )
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should only return OPEN fundraises created by self.user
        self.assertEqual(len(response.data["results"]), 1)
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.post.id
        )

    def test_filtering_by_hub_ids(self):
        """Test filtering by hub_ids"""
        post_hubs_id = self.post.hubs.values_list("id", flat=True).first().__str__()
        other_post_hubs_id = (
            self.other_post.hubs.values_list("id", flat=True).first().__str__()
        )

        url = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("hub_ids=" + post_hubs_id + "," + other_post_hubs_id)
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        # There are exactly 2 posts
        self.assertEqual(len(results), 2)

        url2 = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("hub_ids=" + post_hubs_id)
        )
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data["results"]
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["content_object"]["id"], self.post.id)

        url3 = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("hub_ids=" + other_post_hubs_id)
        )
        response3 = self.client.get(url3)
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        results3 = response3.data["results"]
        self.assertEqual(len(results3), 1)
        self.assertEqual(results3[0]["content_object"]["id"], self.other_post.id)

    def test_filtering_by_min_upvotes(self):
        """Test filtering by min_upvotes"""
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        vote = Vote.objects.create(
            created_by=self.user,
            object_id=self.post.id,
            content_type=post_content_type,
            vote_type=Vote.UPVOTE,
        )

        url = reverse("funding_feed-list") + "?filtering=" + quote("min_upvotes=0")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        # There are exactly 2 posts
        self.assertEqual(len(results), 2)

        url2 = reverse("funding_feed-list") + "?filtering=" + quote("min_upvotes=1")
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data["results"]
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["content_object"]["id"], self.post.id)
        self.assertIn("user_vote", results2[0])
        self.assertEqual(results2[0]["user_vote"]["id"], vote.id)

    def test_filtering_by_min_score(self):
        min_score = min([self.review.score, self.other_review.score])
        max_score = max([self.review.score, self.other_review.score])

        url = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("min_score=" + min_score.__str__())
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        # There are exactly 2 posts
        self.assertEqual(len(results), 2)

        url2 = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("min_score=" + int(min_score + 1).__str__())
        )
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data["results"]
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["content_object"]["id"], self.post.id)

        url3 = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("min_score=" + int(max_score + 1).__str__())
        )
        response3 = self.client.get(url3)
        self.assertEqual(response3.status_code, status.HTTP_200_OK)
        results3 = response3.data["results"]
        self.assertEqual(len(results3), 0)

    def test_filtering_by_verified_authors_only(self):
        url = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("verified_authors_only=false")
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        # There are exactly 2 posts
        self.assertEqual(len(results), 2)

        url2 = (
            reverse("funding_feed-list")
            + "?filtering="
            + quote("verified_authors_only=true")
        )
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data["results"]
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["content_object"]["id"], self.post.id)

    def test_filtering_by_tax_deductible(self):
        url = (
            reverse("funding_feed-list") + "?filtering=" + quote("tax_deductible=false")
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data["results"]
        # There are exactly 2 posts
        self.assertEqual(len(results), 2)

        url2 = (
            reverse("funding_feed-list") + "?filtering=" + quote("tax_deductible=true")
        )
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        results2 = response2.data["results"]
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0]["content_object"]["id"], self.post.id)

    def test_ordering_by_amount_raised(self):
        """Test ordering by amount raised (highest first)"""
        # Create a post with a higher amount raised
        high_amount_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        high_amount_post = ResearchhubPost.objects.create(
            title="High Amount Raised Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_amount_doc,
        )
        high_amount_escrow = Escrow.objects.create(
            amount_holding=1000,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=high_amount_doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=high_amount_doc,
            escrow=high_amount_escrow,
            status=Fundraise.OPEN,
        )

        url = reverse("funding_feed-list") + "?ordering=amount_raised"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        # There are more than 2 posts, but we only care about the order of these two
        self.assertGreater(len(results), 1)

        # The post with the higher amount raised should be first
        first_post_id = results[0]["content_object"]["id"]
        self.assertEqual(first_post_id, high_amount_post.id)

    def test_ordering_by_newest(self):
        """Test ordering by newest"""
        # Create a post with a recent created_date
        newest_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        newest_post = ResearchhubPost.objects.create(
            title="Newest Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=newest_doc,
            created_date=timezone.now() + timezone.timedelta(minutes=5),
        )

        url = reverse("funding_feed-list") + "?ordering=newest"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        # There are more than 2 posts, but we only care about the order of these two
        self.assertGreater(len(results), 1)

        # The newest post should be first
        first_post_id = results[0]["content_object"]["id"]
        self.assertEqual(first_post_id, newest_post.id)

    def test_ordering_by_expiring(self):
        """Test ordering by expiring soon"""
        # Create a post with an expiration date soon
        expiring_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        expiring_post = ResearchhubPost.objects.create(
            title="Expiring Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=expiring_doc,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=expiring_doc,
            end_date=timezone.now() - timezone.timedelta(minutes=1),
            status=Fundraise.OPEN,
        )

        url = reverse("funding_feed-list") + "?ordering=expiring"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        # There are more than 2 posts, but we only care about the order of these two
        self.assertGreater(len(results), 1)

        # The expiring soon post should be first
        first_post_id = results[0]["content_object"]["id"]
        self.assertEqual(first_post_id, expiring_post.id)

    def test_ordering_by_goal_percent(self):
        """Test ordering by goal percent (highest first)"""
        # Create a post with an expiration date soon
        goal_percent_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        goal_percent_post = ResearchhubPost.objects.create(
            title="Goal Percent Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=goal_percent_doc,
        )
        goal_percent_escrow = Escrow.objects.create(
            amount_holding=999 / RSC_TO_USD_RATE,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=goal_percent_doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=goal_percent_doc,
            escrow=goal_percent_escrow,
            goal_amount=1000,
            status=Fundraise.OPEN,
        )

        url = reverse("funding_feed-list") + "?ordering=goal_percent"
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.data["results"]
        # There are more than 2 posts, but we only care about the order of these two
        self.assertGreater(len(results), 1)

        # The expiring soon post should be first
        first_post_id = results[0]["content_object"]["id"]
        self.assertEqual(first_post_id, goal_percent_post.id)
