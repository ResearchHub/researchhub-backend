import uuid
from datetime import timedelta
from unittest.mock import patch

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
from feed.views.journal_feed_view import JournalFeedViewSet
from hub.models import Hub
from paper.related_models.paper_model import Paper
from paper.related_models.paper_version import PaperVersion
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)

User = get_user_model()


class JournalFeedViewSetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )

        # Set up API client
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

        # Create a hub
        self.hub = Hub.objects.create(name="Test Hub")

        # Create papers with different publication statuses

        # Preprint paper
        self.preprint_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.preprint_unified_document.hubs.add(self.hub)

        self.preprint_paper = Paper.objects.create(
            title="Preprint Paper",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=self.preprint_unified_document,
            created_date=timezone.now(),
        )

        self.preprint_version = PaperVersion.objects.create(
            paper=self.preprint_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
            version=1,
            base_doi="10.1234/preprint.12345",
        )

        # Published paper
        self.published_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.published_unified_document.hubs.add(self.hub)

        self.published_paper = Paper.objects.create(
            title="Published Paper",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=self.published_unified_document,
            created_date=timezone.now(),
        )

        self.published_version = PaperVersion.objects.create(
            paper=self.published_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PUBLISHED,
            version=1,
            base_doi="10.1234/published.12345",
        )

        # Non-journal paper (should not appear in feed)
        self.non_journal_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

        self.non_journal_paper = Paper.objects.create(
            title="Non-Journal Paper",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=self.non_journal_unified_document,
            created_date=timezone.now(),
        )

        # Create PaperVersion for non-journal paper (journal=None)
        self.non_journal_version = PaperVersion.objects.create(
            paper=self.non_journal_paper,
            journal=None,  # Not in any journal
            publication_status=PaperVersion.PREPRINT,  # Set publication status
            version=1,
        )

        # Removed journal paper (should not appear in feed)
        self.removed_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )

        self.removed_paper = Paper.objects.create(
            title="Removed Journal Paper",
            uploaded_by=self.user,
            is_public=True,
            is_removed=True,
            is_removed_by_user=False,
            unified_document=self.removed_unified_document,
            created_date=timezone.now(),
        )

        self.removed_version = PaperVersion.objects.create(
            paper=self.removed_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
            version=1,
            base_doi="10.1234/removed.12345",
        )

        # Clear cache before tests
        cache.clear()

    def test_list_journal_feed(self):
        """Test that only journal papers appear in the default feed"""
        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)  # preprint + published

        # Check that returned papers are journal papers
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Preprint Paper", titles)
        self.assertIn("Published Paper", titles)
        self.assertNotIn("Non-Journal Paper", titles)
        self.assertNotIn("Removed Journal Paper", titles)

    def test_filter_by_journal_status_in_journal(self):
        """Test filtering by journal_status=IN_JOURNAL"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"journal_status": "IN_JOURNAL"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 2)  # preprint + published

        # Check that returned papers are journal papers
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Preprint Paper", titles)
        self.assertIn("Published Paper", titles)
        self.assertNotIn("Non-Journal Paper", titles)

    def test_filter_by_journal_status_not_in_journal(self):
        """Test filtering by journal_status=NOT_IN_JOURNAL"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"journal_status": "NOT_IN_JOURNAL"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)  # only non-journal paper

        # Check that returned paper is not a journal paper
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Non-Journal Paper", titles)
        self.assertNotIn("Preprint Paper", titles)
        self.assertNotIn("Published Paper", titles)

    def test_filter_by_journal_status_all(self):
        """Test filtering by journal_status=ALL"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"journal_status": "ALL"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 3)  # all papers except removed

        # Check that all public, non-removed papers are returned
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Preprint Paper", titles)
        self.assertIn("Published Paper", titles)
        self.assertIn("Non-Journal Paper", titles)
        self.assertNotIn("Removed Journal Paper", titles)

    def test_combined_journal_and_publication_status_filters(self):
        """Test combining journal_status and publication_status filters"""
        url = reverse("journal_feed-list")

        # Test IN_JOURNAL + PREPRINT
        response = self.client.get(
            url, {"journal_status": "IN_JOURNAL", "publication_status": "PREPRINT"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Preprint Paper", titles)
        self.assertNotIn("Published Paper", titles)

        # Test IN_JOURNAL + PUBLISHED
        response = self.client.get(
            url, {"journal_status": "IN_JOURNAL", "publication_status": "PUBLISHED"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Published Paper", titles)
        self.assertNotIn("Preprint Paper", titles)

    def test_publication_status_applies_to_non_journal_papers(self):
        """Test that publication_status filter applies to non-journal papers too"""
        url = reverse("journal_feed-list")

        # Create a non-journal paper with PUBLISHED status
        published_non_journal_unified_document = (
            ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        )
        published_non_journal_paper = Paper.objects.create(
            title="Published Non-Journal Paper",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=published_non_journal_unified_document,
            created_date=timezone.now(),
        )
        PaperVersion.objects.create(
            paper=published_non_journal_paper,
            journal=None,  # Not in any journal
            publication_status=PaperVersion.PUBLISHED,
            version=1,
        )

        # Test NOT_IN_JOURNAL + PUBLISHED should return the published non-journal paper
        response = self.client.get(
            url, {"journal_status": "NOT_IN_JOURNAL", "publication_status": "PUBLISHED"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Published Non-Journal Paper", titles)
        self.assertNotIn("Non-Journal Paper", titles)  # PREPRINT status

        # Test NOT_IN_JOURNAL + PREPRINT should return the original non-journal paper
        response = self.client.get(
            url, {"journal_status": "NOT_IN_JOURNAL", "publication_status": "PREPRINT"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        titles = [item["content_object"]["title"] for item in response.data["results"]]
        self.assertIn("Non-Journal Paper", titles)  # PREPRINT status
        self.assertNotIn("Published Non-Journal Paper", titles)

    def test_filter_by_preprint_status(self):
        """Test filtering by PREPRINT publication status"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"publication_status": "PREPRINT"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only include preprint papers
        self.assertEqual(len(response.data["results"]), 1)

        # Verify only the preprint paper is in the response
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.preprint_paper.id
        )

    def test_filter_by_published_status(self):
        """Test filtering by PUBLISHED publication status"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"publication_status": "PUBLISHED"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should only include published papers
        self.assertEqual(len(response.data["results"]), 1)

        # Verify only the published paper is in the response
        self.assertEqual(
            response.data["results"][0]["content_object"]["id"], self.published_paper.id
        )

    def test_filter_by_all_status(self):
        """Test filtering by ALL publication status (default)"""
        url = reverse("journal_feed-list")
        response = self.client.get(url, {"publication_status": "ALL"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should include all journal papers (2 papers)
        self.assertEqual(len(response.data["results"]), 2)

    @patch("feed.views.journal_feed_view.cache")
    def test_journal_feed_cache(self, mock_cache):
        """Test caching functionality for journal feed"""
        # No cache on first request
        mock_cache.get.return_value = None

        url = reverse("journal_feed-list")
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
        # Create a vote for the paper
        paper_content_type = ContentType.objects.get_for_model(Paper)
        vote = Vote.objects.create(
            created_by=self.user,
            object_id=self.preprint_paper.id,
            content_type=paper_content_type,
            vote_type=Vote.UPVOTE,
        )

        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Find the paper in the response
        paper_data = None
        for item in response.data["results"]:
            if item["content_object"]["id"] == self.preprint_paper.id:
                paper_data = item
                break

        self.assertIsNotNone(paper_data)
        self.assertIn("user_vote", paper_data)
        self.assertEqual(paper_data["user_vote"]["id"], vote.id)  # NOSONAR

        # Use the integer value for the vote type, as that's what gets serialized
        vote_type = paper_data["user_vote"]["vote_type"]
        self.assertEqual(vote_type, 1)  # 1 corresponds to UPVOTE

    @patch("feed.views.journal_feed_view.cache")
    def test_add_user_votes_with_cached_response(self, mock_cache):
        """Test that user votes are added even with cached response"""
        # Create a vote for the paper
        paper_content_type = ContentType.objects.get_for_model(Paper)
        vote = Vote.objects.create(
            created_by=self.user,
            object_id=self.preprint_paper.id,
            content_type=paper_content_type,
            vote_type=Vote.UPVOTE,
        )

        # Create a mock cached response without votes
        cached_response = {
            "results": [
                {
                    "id": 1,
                    "content_type": "PAPER",
                    "content_object": {
                        "id": self.preprint_paper.id,
                        "title": "Preprint Paper",
                    },
                    "metrics": {},
                },
                {
                    "id": 2,
                    "content_type": "PAPER",
                    "content_object": {
                        "id": self.published_paper.id,
                        "title": "Published Paper",
                    },
                    "metrics": {},
                },
            ]
        }

        mock_cache.get.return_value = cached_response

        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify the user votes were added to the cached response
        paper_data = None
        for item in response.data["results"]:
            if item["content_object"]["id"] == self.preprint_paper.id:
                paper_data = item
                break

        self.assertIsNotNone(paper_data)
        self.assertIn("user_vote", paper_data)
        # Verify the vote ID matches the one we created
        self.assertEqual(paper_data["user_vote"]["id"], vote.id)  # NOSONAR

    def test_pagination(self):
        """Test journal feed pagination"""
        # Create additional papers for pagination testing
        for i in range(25):
            unified_doc = ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            )
            paper = Paper.objects.create(
                title=f"Test Journal Paper {i}",
                uploaded_by=self.user,
                is_public=True,
                is_removed=False,
                is_removed_by_user=False,
                unified_document=unified_doc,
                created_date=timezone.now(),
            )
            PaperVersion.objects.create(
                paper=paper,
                journal=PaperVersion.RESEARCHHUB,
                publication_status=PaperVersion.PREPRINT,
                version=1,
                base_doi=f"10.1234/paper{i}.12345",
            )

        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 20)  # Default page size
        self.assertIsNotNone(response.data["next"])
        self.assertIsNone(response.data["previous"])

        # Test going to page 2
        page_2_url = response.data["next"]
        response_page_2 = self.client.get(page_2_url)

        self.assertEqual(response_page_2.status_code, status.HTTP_200_OK)
        self.assertEqual(
            len(response_page_2.data["results"]), 7
        )  # 27 total items, 7 on page 2
        self.assertIsNone(response_page_2.data["next"])
        self.assertIsNotNone(response_page_2.data["previous"])

    def test_unique_base_doi(self):
        """Test that journal feed returns only one paper per base_doi (the latest one)"""
        # Create a common base_doi for multiple papers
        base_doi = "10.1234/test.12345"

        # Create papers with the same base_doi but different creation dates
        # Paper 1 - Oldest
        oldest_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        oldest_unified_document.hubs.add(self.hub)

        oldest_paper = Paper.objects.create(
            title="Oldest Paper - Same DOI",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=oldest_unified_document,
            created_date=timezone.now() - timedelta(days=2),
        )

        oldest_version = PaperVersion.objects.create(  # noqa: F841
            paper=oldest_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
            version=1,
            base_doi=base_doi,
        )

        # Paper 2 - Middle
        middle_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        middle_unified_document.hubs.add(self.hub)

        middle_paper = Paper.objects.create(
            title="Middle Paper - Same DOI",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=middle_unified_document,
            created_date=timezone.now() - timedelta(days=1),
        )

        middle_version = PaperVersion.objects.create(  # noqa: F841
            paper=middle_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
            version=2,
            base_doi=base_doi,
        )

        # Paper 3 - Newest (should be the one that appears in feed)
        newest_unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        newest_unified_document.hubs.add(self.hub)

        newest_paper = Paper.objects.create(
            title="Newest Paper - Same DOI",
            uploaded_by=self.user,
            is_public=True,
            is_removed=False,
            is_removed_by_user=False,
            unified_document=newest_unified_document,
            created_date=timezone.now(),
        )

        newest_version = PaperVersion.objects.create(  # noqa: F841
            paper=newest_paper,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
            version=3,
            base_doi=base_doi,
        )

        # Clear cache before testing
        cache.clear()

        # Make request to journal feed
        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check for papers with the same base_doi
        papers_with_base_doi = []
        for item in response.data["results"]:
            paper_id = item["content_object"]["id"]
            paper = Paper.objects.get(id=paper_id)
            paper_version = paper.version
            if paper_version.base_doi == base_doi:
                papers_with_base_doi.append(paper)

        # Verify that only one paper with this base_doi is returned
        self.assertEqual(len(papers_with_base_doi), 1)

        # Verify that it's the newest paper
        self.assertEqual(papers_with_base_doi[0].id, newest_paper.id)

        # The older papers with the same DOI should not be in the response
        paper_ids = [item["content_object"]["id"] for item in response.data["results"]]
        self.assertNotIn(oldest_paper.id, paper_ids)
        self.assertNotIn(middle_paper.id, paper_ids)

    def test_cache_key_with_publication_status(self):
        """Test that cache keys are different for different publication status values"""
        # Clear cache before testing
        cache.clear()

        # Create a test instance
        viewset = JournalFeedViewSet()

        # Mock requests with different publication status values

        factory = APIRequestFactory()

        # Test with ALL status (default)
        all_request = factory.get("/api/journal_feed/")
        all_request = Request(all_request)
        all_request.user = self.user

        # Test with PREPRINT status
        preprint_request = factory.get("/api/journal_feed/?publication_status=PREPRINT")
        preprint_request = Request(preprint_request)
        preprint_request.user = self.user

        # Test with PUBLISHED status
        published_request = factory.get(
            "/api/journal_feed/?publication_status=PUBLISHED"
        )
        published_request = Request(published_request)
        published_request.user = self.user

        # Generate cache keys for different statuses
        all_status = all_request.query_params.get("publication_status", "ALL").lower()
        preprint_status = preprint_request.query_params.get(
            "publication_status", "ALL"
        ).lower()
        published_status = published_request.query_params.get(
            "publication_status", "ALL"
        ).lower()

        all_cache_key = viewset.get_cache_key(all_request, f"journal_{all_status}")
        preprint_cache_key = viewset.get_cache_key(
            preprint_request, f"journal_{preprint_status}"
        )
        published_cache_key = viewset.get_cache_key(
            published_request, f"journal_{published_status}"
        )

        # Verify the cache keys are different
        self.assertNotEqual(all_cache_key, preprint_cache_key)
        self.assertNotEqual(all_cache_key, published_cache_key)
        self.assertNotEqual(preprint_cache_key, published_cache_key)

        # Verify the cache keys contain the correct publication status
        self.assertIn("journal_all", all_cache_key)
        self.assertIn("journal_preprint", preprint_cache_key)
        self.assertIn("journal_published", published_cache_key)

    def test_api_requests_with_different_publication_status(self):
        """Test API responses for different publication status filters"""
        # Clear cache before making requests
        cache.clear()

        # Make requests with different publication status
        url = reverse("journal_feed-list")

        # Make request with ALL status
        all_response = self.client.get(url)
        self.assertEqual(all_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(all_response.data["results"]), 2)  # Both papers

        # Make request with PREPRINT status
        preprint_response = self.client.get(url, {"publication_status": "PREPRINT"})
        self.assertEqual(preprint_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(preprint_response.data["results"]), 1)  # Only preprint

        # Make request with PUBLISHED status
        published_response = self.client.get(url, {"publication_status": "PUBLISHED"})
        self.assertEqual(published_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(published_response.data["results"]), 1)  # Only published
