from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.services import PaperMetricsEnrichmentService
from paper.models import Paper


class PaperMetricsEnrichmentServiceTests(TestCase):
    def setUp(self):
        self.paper = Paper.objects.create(
            title="Paper with DOI",
            doi="10.1038/news.2011.490",
            paper_publish_date=timezone.now() - timedelta(days=3),
        )

        self.paper_without_doi = Paper.objects.create(
            title="Paper without DOI",
            paper_publish_date=timezone.now() - timedelta(days=2),
        )

        self.mapped_metrics = {
            "facebook_count": 5,
            "twitter_count": 138,
            "score": 140.5,
        }

        # Sample GitHub mentions response
        self.sample_github_response = {
            "total_mentions": 15,
            "term": "10.1038/news.2011.490",
            "breakdown": {
                "issues": 10,
                "commits": 3,
                "repositories": 2,
            },
        }

        # Sample Bluesky response
        self.sample_bluesky_response = {
            "post_count": 5,
            "total_likes": 120,
            "total_reposts": 30,
            "total_replies": 15,
            "total_quotes": 8,
            "posts": [
                {
                    "uri": "at://did:plc:abc123/app.bsky.feed.post/xyz",
                    "cid": "bafyreigxyz",
                    "author_handle": "researcher.bsky.social",
                    "author_display_name": "Dr. Researcher",
                    "author_did": "did:plc:abc123",
                    "text": "Great paper on DOI 10.1038/news.2011.490",
                    "created_at": "2024-01-15T10:30:00Z",
                    "like_count": 50,
                    "repost_count": 10,
                    "reply_count": 5,
                    "quote_count": 3,
                },
            ],
        }

        # Create mocks for client and mapper
        self.mock_client = Mock()
        self.mock_mapper = Mock()
        self.mock_github_client = Mock()
        self.mock_bluesky_client = Mock()
        self.mock_x_client = Mock()

        self.service = PaperMetricsEnrichmentService(
            github_metrics_client=self.mock_github_client,
            bluesky_metrics_client=self.mock_bluesky_client,
            x_metrics_client=self.mock_x_client,
        )

    def test_get_recent_papers_with_dois(self):
        """Test querying recent papers with DOIs."""
        # Act
        papers = self.service.get_recent_papers_with_dois(days=7)

        # Assert
        self.assertIn(self.paper.id, papers)
        # Verify all returned values are integers (paper IDs)
        self.assertTrue(all(isinstance(pid, int) for pid in papers))

    def test_get_recent_papers_excludes_old_papers(self):
        """Test that old papers are excluded."""
        # Arrange
        # Create old paper (will have auto_now_add set to now)
        old_paper = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old",
            paper_publish_date=timezone.now() - timedelta(days=30),
        )

        # Act
        papers = self.service.get_recent_papers_with_dois(days=7)

        # Assert
        self.assertNotIn(
            old_paper.id,
            papers,
            f"Old paper (published {old_paper.paper_publish_date}) "
            f"should be excluded from papers from last 7 days",
        )

    def test_enrich_paper_with_github_mentions(self):
        """
        Test successful enrichment of a paper with GitHub mentions.
        """
        # Arrange
        self.mock_github_client.get_mentions.return_value = self.sample_github_response

        # Act
        result = self.service.enrich_paper_with_github_mentions(self.paper)

        # Assert
        self.assertEqual(result.status, "success")
        self.assertEqual(
            result.metrics, {"github_mentions": self.sample_github_response}
        )

        # Verify client was called with the correct terms (DOI and title)
        self.mock_github_client.get_mentions.assert_called_once_with(
            [self.paper.doi, self.paper.title], search_areas=["code"]
        )

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertIsNotNone(self.paper.external_metadata)
        self.assertIn("metrics", self.paper.external_metadata)
        self.assertIn("github_mentions", self.paper.external_metadata["metrics"])
        self.assertEqual(
            self.paper.external_metadata["metrics"]["github_mentions"],
            self.sample_github_response,
        )

    def test_enrich_paper_with_github_mentions_not_found(self):
        """
        Test GitHub enrichment when no mentions are found.
        """
        # Arrange
        self.mock_github_client.get_mentions.return_value = None

        # Act
        result = self.service.enrich_paper_with_github_mentions(self.paper)

        # Assert
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_github_mentions")

        # Verify client was called
        self.mock_github_client.get_mentions.assert_called_once_with(
            [self.paper.doi, self.paper.title], search_areas=["code"]
        )

    def test_enrich_paper_with_github_mentions_preserves_existing_metadata(self):
        """
        Test that GitHub enrichment preserves existing metadata and existing metrics.
        """
        # Arrange
        self.paper.external_metadata = {
            "existing_key": "existing_value",
            "metrics": {
                "twitter_count": 100,
            },
        }
        self.paper.save()

        self.mock_github_client.get_mentions.return_value = self.sample_github_response

        # Act
        result = self.service.enrich_paper_with_github_mentions(self.paper)

        # Assert
        self.assertEqual(result.status, "success")

        # Verify existing metadata is preserved
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.external_metadata["existing_key"], "existing_value")

        # Verify both old and new metrics exist
        self.assertIn("metrics", self.paper.external_metadata)

        # Verify existing metrics are preserved (not overwritten)
        self.assertEqual(self.paper.external_metadata["metrics"]["twitter_count"], 100)

        # Verify new GitHub metrics were added
        self.assertIn("github_mentions", self.paper.external_metadata["metrics"])
        self.assertEqual(
            self.paper.external_metadata["metrics"]["github_mentions"],
            self.sample_github_response,
        )

    def test_enrich_paper_with_github_mentions_handles_api_error(self):
        """
        Test GitHub enrichment handles API errors gracefully.
        """
        # Arrange
        self.mock_github_client.get_mentions.side_effect = Exception("D'oh!")

        # Act
        result = self.service.enrich_paper_with_github_mentions(self.paper)

        # Assert
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "D'oh!")

        # Verify client was called
        self.mock_github_client.get_mentions.assert_called_once_with(
            [self.paper.doi, self.paper.title], search_areas=["code"]
        )

    def test_enrich_paper_with_bluesky_success(self):
        """
        Test successful enrichment of a paper with Bluesky metrics.
        """
        # Arrange
        self.mock_bluesky_client.get_metrics.return_value = self.sample_bluesky_response

        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper)

        # Assert
        self.assertEqual(result.status, "success")
        self.assertEqual(result.metrics, {"bluesky": self.sample_bluesky_response})

        # Verify client was called with the correct DOI
        self.mock_bluesky_client.get_metrics.assert_called_once_with(self.paper.doi)

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertIsNotNone(self.paper.external_metadata)
        self.assertIn("metrics", self.paper.external_metadata)
        self.assertIn("bluesky", self.paper.external_metadata["metrics"])
        self.assertEqual(
            self.paper.external_metadata["metrics"]["bluesky"],
            self.sample_bluesky_response,
        )

    def test_enrich_paper_with_bluesky_not_found(self):
        """
        Test Bluesky enrichment when no posts are found.
        """
        # Arrange
        self.mock_bluesky_client.get_metrics.return_value = None

        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper)

        # Assert
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_bluesky_posts")

        # Verify client was called
        self.mock_bluesky_client.get_metrics.assert_called_once_with(self.paper.doi)

    def test_enrich_paper_with_bluesky_no_doi(self):
        """
        Test Bluesky enrichment is skipped for papers without DOI.
        """
        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper_without_doi)

        # Assert
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "no_doi")

        # Verify client was not called
        self.mock_bluesky_client.get_metrics.assert_not_called()

    def test_enrich_paper_with_bluesky_preserves_existing_metadata(self):
        """
        Test that Bluesky enrichment preserves existing metadata and existing metrics.
        """
        # Arrange
        self.paper.external_metadata = {
            "existing_key": "existing_value",
            "metrics": {
                "github_mentions": {"total_mentions": 10},
            },
        }
        self.paper.save()

        self.mock_bluesky_client.get_metrics.return_value = self.sample_bluesky_response

        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper)

        # Assert
        self.assertEqual(result.status, "success")

        # Verify existing metadata is preserved
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.external_metadata["existing_key"], "existing_value")

        # Verify both old and new metrics exist
        self.assertIn("metrics", self.paper.external_metadata)

        # Verify existing metrics are preserved (not overwritten)
        self.assertEqual(
            self.paper.external_metadata["metrics"]["github_mentions"][
                "total_mentions"
            ],
            10,
        )

        # Verify new Bluesky metrics were added
        self.assertIn("bluesky", self.paper.external_metadata["metrics"])
        self.assertEqual(
            self.paper.external_metadata["metrics"]["bluesky"],
            self.sample_bluesky_response,
        )

    def test_enrich_paper_with_bluesky_handles_api_error(self):
        """
        Test Bluesky enrichment handles API errors gracefully.
        """
        # Arrange
        self.mock_bluesky_client.get_metrics.side_effect = Exception(
            "Bluesky API error"
        )

        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper)

        # Assert
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "Bluesky API error")

        # Verify client was called
        self.mock_bluesky_client.get_metrics.assert_called_once_with(self.paper.doi)

    def test_enrich_paper_with_x_success(self):
        """
        Test successful enrichment of a paper with X metrics.
        """
        # Arrange
        sample_x_response = {
            "post_count": 10,
            "total_likes": 200,
            "total_reposts": 50,
            "total_replies": 25,
            "total_quotes": 12,
            "total_impressions": 5000,
            "terms": [self.paper.doi, self.paper.title],
            "posts": [
                {
                    "id": "1234567890",
                    "text": "Great paper on DOI 10.1038/news.2011.490",
                    "author_id": "123456",
                    "created_at": "2024-01-15T10:30:00Z",
                    "like_count": 50,
                    "repost_count": 10,
                    "reply_count": 5,
                    "quote_count": 3,
                    "impression_count": 1000,
                },
            ],
        }
        self.mock_x_client.get_metrics.return_value = sample_x_response

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "success")
        self.assertEqual(result.metrics, {"x": sample_x_response})

        # Verify client was called with DOI and title terms (like GitHub)
        self.mock_x_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title],
            external_source=self.paper.external_source,
            hub_slugs=list(self.paper.hubs.values_list("slug", flat=True)),
        )

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertIsNotNone(self.paper.external_metadata)
        self.assertIn("metrics", self.paper.external_metadata)
        self.assertIn("x", self.paper.external_metadata["metrics"])
        self.assertEqual(
            self.paper.external_metadata["metrics"]["x"],
            sample_x_response,
        )

    def test_enrich_paper_with_x_not_found(self):
        """
        Test X enrichment when no posts are found.
        """
        # Arrange
        self.mock_x_client.get_metrics.return_value = None

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_x_posts")

        # Verify client was called with DOI and title terms
        self.mock_x_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title],
            external_source=self.paper.external_source,
            hub_slugs=list(self.paper.hubs.values_list("slug", flat=True)),
        )

    def test_enrich_paper_with_x_no_doi_uses_title(self):
        """
        Test X enrichment uses title when paper has no DOI.
        """
        # Arrange - paper_without_doi still has a title
        self.mock_x_client.get_metrics.return_value = None

        # Act
        result = self.service.enrich_paper_with_x(self.paper_without_doi)

        # Assert - should still try to search with title
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_x_posts")

        # Verify client was called with just the title
        self.mock_x_client.get_metrics.assert_called_once_with(
            [self.paper_without_doi.title],
            external_source=self.paper_without_doi.external_source,
            hub_slugs=list(self.paper_without_doi.hubs.values_list("slug", flat=True)),
        )

    def test_enrich_paper_with_x_handles_api_error(self):
        """
        Test X enrichment handles API errors gracefully.
        """
        # Arrange
        self.mock_x_client.get_metrics.side_effect = Exception("X API error")

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "error")
        self.assertEqual(result.reason, "X API error")

        # Verify client was called with DOI and title terms
        self.mock_x_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title],
            external_source=self.paper.external_source,
            hub_slugs=list(self.paper.hubs.values_list("slug", flat=True)),
        )
