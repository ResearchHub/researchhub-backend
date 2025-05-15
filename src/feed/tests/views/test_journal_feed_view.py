import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from discussion.reaction_models import Vote as GrmVote
from hub.models import Hub
from paper.related_models.paper_model import Paper, PaperVersion
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
        )

        # Clear cache before tests
        cache.clear()

    def test_list_journal_feed(self):
        """Test that journal feed returns all papers in the ResearchHub journal"""
        url = reverse("journal_feed-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should include all non-removed journal papers (2 papers)
        self.assertEqual(len(response.data["results"]), 2)

        # Verify the papers are in the response
        paper_ids = []
        for item in response.data["results"]:
            paper_ids.append(item["content_object"]["id"])

        self.assertIn(self.preprint_paper.id, paper_ids)
        self.assertIn(self.published_paper.id, paper_ids)

        # Verify non-journal and removed papers are not included
        self.assertNotIn(self.non_journal_paper.id, paper_ids)
        self.assertNotIn(self.removed_paper.id, paper_ids)

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
        vote = GrmVote.objects.create(
            created_by=self.user,
            object_id=self.preprint_paper.id,
            content_type=paper_content_type,
            vote_type=GrmVote.UPVOTE,
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
        self.assertEqual(paper_data["user_vote"]["id"], vote.id)

        # Use the integer value for the vote type, as that's what gets serialized
        vote_type = paper_data["user_vote"]["vote_type"]
        self.assertEqual(vote_type, 1)  # 1 corresponds to UPVOTE

    @patch("feed.views.journal_feed_view.cache")
    def test_add_user_votes_with_cached_response(self, mock_cache):
        """Test that user votes are added even with cached response"""
        # Create a vote for the paper
        paper_content_type = ContentType.objects.get_for_model(Paper)
        vote = GrmVote.objects.create(
            created_by=self.user,
            object_id=self.preprint_paper.id,
            content_type=paper_content_type,
            vote_type=GrmVote.UPVOTE,
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
        self.assertEqual(paper_data["user_vote"]["id"], vote.id)

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
