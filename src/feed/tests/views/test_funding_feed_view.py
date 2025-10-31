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

from discussion.models import Vote
from hub.models import Hub
from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import MORALIS
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.grant_application_model import GrantApplication
from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.models import Escrow
from researchhub_document.related_models.constants.document_type import GRANT, PREREGISTRATION
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

        # Create a grant for testing applications
        self.grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.unified_document,
            amount=1000,
            currency=USD,
            organization="Test Organization",
            description="Test grant description",
            status=Grant.OPEN,
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

        # Create fundraises for testing
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
        cache_key = "funding_feed:latest:all:all:none:1-20"
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
        cache_key = "funding_feed:latest:all:all:none:1-20"
        cached_response = cache.get(cache_key)

        # Cache should be None since created_by disables caching
        self.assertIsNone(cached_response)

    def test_upvotes_sorting(self):
        """Test sorting by upvotes (descending)"""
        # Create posts with different upvote counts
        from researchhub_document.related_models.document_filter_model import DocumentFilter
        
        # Post with high upvotes
        high_upvotes_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        high_upvotes_filter = DocumentFilter.objects.create(
            upvoted_all=100
        )
        high_upvotes_doc.document_filter = high_upvotes_filter
        high_upvotes_doc.save()
        
        ResearchhubPost.objects.create(
            title="High Upvotes Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_upvotes_doc,
        )
        
        # Post with low upvotes
        low_upvotes_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        low_upvotes_filter = DocumentFilter.objects.create(
            upvoted_all=10
        )
        low_upvotes_doc.document_filter = low_upvotes_filter
        low_upvotes_doc.save()
        
        ResearchhubPost.objects.create(
            title="Low Upvotes Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=low_upvotes_doc,
        )
        
        # Test sorting by upvotes
        url = reverse("funding_feed-list")
        response = self.client.get(url, {"ordering": "upvotes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should be sorted by upvotes descending
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)
        
        # Find our test posts in the results
        high_upvotes_found = False
        low_upvotes_found = False
        high_upvotes_index = -1
        low_upvotes_index = -1
        
        for i, result in enumerate(results):
            # Check both direct title and content_object title
            title = result.get("title") or result.get("content_object", {}).get("title", "")
            if title == "High Upvotes Post":
                high_upvotes_found = True
                high_upvotes_index = i
            elif title == "Low Upvotes Post":
                low_upvotes_found = True
                low_upvotes_index = i
        
        self.assertTrue(high_upvotes_found)
        self.assertTrue(low_upvotes_found)
        self.assertLess(high_upvotes_index, low_upvotes_index)

    def test_most_applicants_sorting(self):
        """Test sorting by most applicants (descending)"""
        # Create posts with different application counts
        # Post with many applications
        many_apps_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Many Applications Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=many_apps_doc,
        )
        
        # Create a fundraise for this post
        many_apps_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=many_apps_doc,
            goal_amount=1000,
            goal_currency=USD,
        )
        
        # Create multiple contributors for the fundraise
        for i in range(3):
            # Create a separate user for each contribution
            contributor = User.objects.create_user(
                username=f"contributor{i}",
                password=uuid.uuid4().hex
            )
            # Create a purchase/contribution to the fundraise
            Purchase.objects.create(
                user=contributor,
                item=many_apps_fundraise,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                purchase_method=Purchase.OFF_CHAIN,
                amount="100",
            )
        
        # Post with few applications
        few_apps_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Few Applications Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=few_apps_doc,
        )
        
        # Create a fundraise for this post
        few_apps_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=few_apps_doc,
            goal_amount=500,
            goal_currency=USD,
        )
        
        # Create one contributor for the fundraise
        contributor = User.objects.create_user(
            username="few_contributor",
            password=uuid.uuid4().hex
        )
        # Create a purchase/contribution to the fundraise
        Purchase.objects.create(
            user=contributor,
            item=few_apps_fundraise,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            purchase_method=Purchase.OFF_CHAIN,
            amount="50",
        )
        
        # Test sorting by most applicants
        url = reverse("funding_feed-list")
        response = self.client.get(url, {"ordering": "most_applicants"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should be sorted by application count descending
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)
        
        # Find our test posts in the results
        many_apps_found = False
        few_apps_found = False
        many_apps_index = -1
        few_apps_index = -1
        
        for i, result in enumerate(results):
            # Check both direct title and content_object title
            title = result.get("title") or result.get("content_object", {}).get("title", "")
            if title == "Many Applications Post":
                many_apps_found = True
                many_apps_index = i
            elif title == "Few Applications Post":
                few_apps_found = True
                few_apps_index = i
        
        self.assertTrue(many_apps_found)
        self.assertTrue(few_apps_found)
        self.assertLess(many_apps_index, few_apps_index)

    def test_amount_raised_sorting(self):
        """Test sorting by amount raised (descending)"""
        from reputation.models import Escrow
        
        # Post with high amount raised
        high_amount_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="High Amount Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=high_amount_doc,
        )
        
        # Create fundraise first
        high_amount_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=high_amount_doc,
            goal_amount=1000,
            goal_currency=USD,
        )
        
        # Create escrow with high amount
        from django.contrib.contenttypes.models import ContentType
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        
        high_amount_escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=500,
            amount_paid=300,
            content_type=fundraise_content_type,
            object_id=high_amount_fundraise.id,
        )
        
        # Link escrow to fundraise
        high_amount_fundraise.escrow = high_amount_escrow
        high_amount_fundraise.save()
        
        # Post with low amount raised
        low_amount_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION
        )
        ResearchhubPost.objects.create(
            title="Low Amount Post",
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=low_amount_doc,
        )
        
        # Create fundraise first
        low_amount_fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=low_amount_doc,
            goal_amount=500,
            goal_currency=USD,
        )
        
        # Create escrow with low amount
        low_amount_escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=100,
            amount_paid=50,
            content_type=fundraise_content_type,
            object_id=low_amount_fundraise.id,
        )
        
        # Link escrow to fundraise
        low_amount_fundraise.escrow = low_amount_escrow
        low_amount_fundraise.save()
        
        # Test sorting by amount raised
        url = reverse("funding_feed-list")
        response = self.client.get(url, {"ordering": "amount_raised"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Should be sorted by amount raised descending
        results = response.data["results"]
        self.assertGreaterEqual(len(results), 2)
        
        # Find our test posts in the results
        high_amount_found = False
        low_amount_found = False
        high_amount_index = -1
        low_amount_index = -1
        
        for i, result in enumerate(results):
            # Check both direct title and content_object title
            title = result.get("title") or result.get("content_object", {}).get("title", "")
            if title == "High Amount Post":
                high_amount_found = True
                high_amount_index = i
            elif title == "Low Amount Post":
                low_amount_found = True
                low_amount_index = i
        
        self.assertTrue(high_amount_found)
        self.assertTrue(low_amount_found)
        self.assertLess(high_amount_index, low_amount_index)

    def test_ordering_validation(self):
        """Test that FundOrderingFilter handles different ordering scenarios correctly."""
        from feed.filters import FundOrderingFilter
        from unittest.mock import Mock, patch
        
        filter_instance = FundOrderingFilter()
        factory = APIRequestFactory()
        mock_queryset = Mock()
        mock_view = Mock()
        
        # Setup view with ordering_fields
        mock_view.ordering_fields = ['best', 'upvotes', 'most_applicants', 'amount_raised']
        mock_view.ordering = 'best'
        mock_view.is_grant_view = False
        
        # Test custom sorting (upvotes) - patch the specific sorting method
        request = factory.get('/?ordering=upvotes')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_upvotes_sorting') as mock_upvotes:
            mock_upvotes.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            mock_upvotes.assert_called_once_with(mock_queryset)
        
        # Test newest sorting (default - no ordering param)
        request = factory.get('/')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_newest_sorting') as mock_newest:
            mock_newest.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            # Check that it was called with queryset and model_config
            self.assertEqual(mock_newest.call_count, 1)
            args = mock_newest.call_args[0]
            self.assertEqual(args[0], mock_queryset)
            self.assertIn('model_class', args[1])  # model_config has model_class
        
        # Test best sorting (explicit best)
        request = factory.get('/?ordering=best')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_best_sorting') as mock_best:
            mock_best.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            # Check that it was called with queryset and model_config
            self.assertEqual(mock_best.call_count, 1)
            args = mock_best.call_args[0]
            self.assertEqual(args[0], mock_queryset)
            self.assertIn('model_class', args[1])  # model_config has model_class
        
        # Test with '-' prefix - should be stripped and work
        request = factory.get('/?ordering=-upvotes')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_upvotes_sorting') as mock_upvotes:
            mock_upvotes.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            mock_upvotes.assert_called_once_with(mock_queryset)
        
        # Test comma-separated values - should take first field
        request = factory.get('/?ordering=upvotes,created_date')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_upvotes_sorting') as mock_upvotes:
            mock_upvotes.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            mock_upvotes.assert_called_once_with(mock_queryset)
        
        # Test whitespace handling
        request = factory.get('/?ordering= upvotes ')
        drf_request = Request(request)
        with patch.object(filter_instance, '_apply_upvotes_sorting') as mock_upvotes:
            mock_upvotes.return_value = mock_queryset
            filter_instance.filter_queryset(drf_request, mock_queryset, mock_view)
            mock_upvotes.assert_called_once_with(mock_queryset)

    def test_ordering_validation_integration(self):
        """Test ordering validation through the actual API endpoint."""
        # Test valid ordering
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "upvotes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test invalid ordering - should fall back to default (best)
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "invalid_field"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test with '-' prefix - should work
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "-upvotes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Test multiple fields - should take first valid one
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "invalid_field,upvotes"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def _create_fundraise_post(self, title, amount, status, created_date=None):
        """Helper to create a fundraise post for testing"""
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        post = ResearchhubPost.objects.create(
            title=title,
            created_by=self.user,
            document_type=PREREGISTRATION,
            unified_document=doc,
        )
        if created_date:
            ResearchhubPost.objects.filter(id=post.id).update(created_date=created_date)
            post.refresh_from_db()
        
        escrow = Escrow.objects.create(
            amount_holding=amount,
            amount_paid=0,
            hold_type=Escrow.FUNDRAISE,
            created_by=self.user,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=doc.id,
        )
        Fundraise.objects.create(
            created_by=self.user,
            unified_document=doc,
            escrow=escrow,
            status=status,
            goal_amount=amount * 2,
            goal_currency=USD,
        )
        return post.id
    
    def test_best_sorting_orders_by_open_and_amount_first(self):
        """Test best sorting: open items sorted by amount descending"""
        high = self._create_fundraise_post("High", 1000, Fundraise.OPEN)
        low = self._create_fundraise_post("Low", 100, Fundraise.OPEN)
        
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "best"})
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        
        self.assertLess(result_ids.index(high), result_ids.index(low))
    
    def test_best_sorting_orders_closed_by_date(self):
        """Test best sorting: closed items sorted by date descending"""
        old = self._create_fundraise_post(
            "Old", 1000, Fundraise.COMPLETED, 
            timezone.now() - timezone.timedelta(days=5)
        )
        new = self._create_fundraise_post("New", 100, Fundraise.COMPLETED)
        
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "best"})
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        
        self.assertLess(result_ids.index(new), result_ids.index(old))
    
    def test_best_sorting_orders_shows_closed_after_open(self):
        """Test best sorting: all open items appear before closed items"""
        open_item = self._create_fundraise_post("Open", 100, Fundraise.OPEN)
        closed_item = self._create_fundraise_post("Closed", 1000, Fundraise.COMPLETED)
        
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "best"})
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        
        self.assertLess(result_ids.index(open_item), result_ids.index(closed_item))
    
    def test_best_sorting_ignores_historical_fundraises(self):
        """Test best sorting: only counts open fundraise amount, not historical closed"""
        # Post with $10k closed + $50 open
        doc = ResearchhubUnifiedDocument.objects.create(document_type=PREREGISTRATION)
        post_historical = ResearchhubPost.objects.create(
            title="Historical", created_by=self.user, 
            document_type=PREREGISTRATION, unified_document=doc
        )
        ct = ContentType.objects.get_for_model(ResearchhubUnifiedDocument)
        
        # Closed fundraise $10k
        Fundraise.objects.create(
            created_by=self.user, unified_document=doc, status=Fundraise.COMPLETED,
            escrow=Escrow.objects.create(
                amount_holding=0, amount_paid=10000, hold_type=Escrow.FUNDRAISE,
                created_by=self.user, content_type=ct, object_id=doc.id
            )
        )
        # Open fundraise $50
        Fundraise.objects.create(
            created_by=self.user, unified_document=doc, status=Fundraise.OPEN,
            escrow=Escrow.objects.create(
                amount_holding=50, amount_paid=0, hold_type=Escrow.FUNDRAISE,
                created_by=self.user, content_type=ct, object_id=doc.id
            )
        )
        
        # Post with $500 open only
        post_current = self._create_fundraise_post("Current", 500, Fundraise.OPEN)
        
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "best"})
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        
        # $500 open should rank higher than $50 open (ignoring $10k closed)
        self.assertLess(result_ids.index(post_current), result_ids.index(post_historical.id))

    def test_ended_ordering_shows_closed_fundraises(self):
        """Test that ordering=ended shows only closed/completed fundraises"""
        open_id = self._create_fundraise_post("Open", 1000, Fundraise.OPEN)
        closed_id = self._create_fundraise_post("Closed", 500, Fundraise.COMPLETED)
        
        response = self.client.get(reverse("funding_feed-list"), {"ordering": "ended"})
        result_ids = [r["content_object"]["id"] for r in response.data["results"]]
        
        self.assertIn(closed_id, result_ids)
        self.assertNotIn(open_id, result_ids)

