from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.services import PaperMetricsEnrichmentService
from paper.models import Paper
from paper.related_models.x_post_model import XPost


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

        # Verify client was called with the correct terms (DOI and title)
        self.mock_bluesky_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title]
        )

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

        # Verify client was called with DOI and title terms
        self.mock_bluesky_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title]
        )

    def test_enrich_paper_with_bluesky_no_doi_uses_title(self):
        """
        Test Bluesky enrichment uses title when paper has no DOI.
        """
        # Arrange - paper_without_doi still has a title
        self.mock_bluesky_client.get_metrics.return_value = None

        # Act
        result = self.service.enrich_paper_with_bluesky(self.paper_without_doi)

        # Assert - should still try to search with title
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_bluesky_posts")

        # Verify client was called with just the title
        self.mock_bluesky_client.get_metrics.assert_called_once_with(
            [self.paper_without_doi.title]
        )

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

        # Verify client was called with DOI and title terms
        self.mock_bluesky_client.get_metrics.assert_called_once_with(
            [self.paper.doi, self.paper.title]
        )

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

    def test_enrich_paper_with_x_returns_retryable_error_on_rate_limit(self):
        """
        Test X enrichment returns retryable_error status on 429 rate limit.
        """
        # Arrange - create an exception with a response that has status_code 429
        mock_response = Mock()
        mock_response.status_code = 429
        rate_limit_error = Exception("Rate limit exceeded")
        rate_limit_error.response = mock_response
        self.mock_x_client.get_metrics.side_effect = rate_limit_error

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "retryable_error")
        self.assertEqual(result.reason, "Rate limit exceeded")

    def test_enrich_paper_with_x_returns_retryable_error_on_503(self):
        """
        Test X enrichment returns retryable_error status on 503 service unavailable.
        """
        # Arrange - create an exception with a response that has status_code 503
        mock_response = Mock()
        mock_response.status_code = 503
        service_unavailable_error = Exception("Service unavailable")
        service_unavailable_error.response = mock_response
        self.mock_x_client.get_metrics.side_effect = service_unavailable_error

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "retryable_error")
        self.assertEqual(result.reason, "Service unavailable")

    def test_enrich_paper_with_x_saves_posts_to_database(self):
        """
        Test that X enrichment saves individual posts to the XPost model.
        """
        # Arrange
        sample_x_response = {
            "post_count": 2,
            "total_likes": 75,
            "total_reposts": 15,
            "total_replies": 8,
            "total_quotes": 4,
            "total_impressions": 2000,
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
                {
                    "id": "9876543210",
                    "text": "Another mention of the paper",
                    "author_id": "654321",
                    "created_at": "2024-01-16T14:00:00Z",
                    "like_count": 25,
                    "repost_count": 5,
                    "reply_count": 3,
                    "quote_count": 1,
                    "impression_count": 1000,
                },
            ],
        }
        self.mock_x_client.get_metrics.return_value = sample_x_response

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "success")

        # Verify XPost records were created
        x_posts = XPost.objects.filter(paper=self.paper)
        self.assertEqual(x_posts.count(), 2)

        # Verify first post
        post1 = x_posts.get(post_id="1234567890")
        self.assertEqual(post1.text, "Great paper on DOI 10.1038/news.2011.490")
        self.assertEqual(post1.author_id, "123456")
        self.assertEqual(post1.like_count, 50)
        self.assertEqual(post1.repost_count, 10)
        self.assertEqual(post1.reply_count, 5)
        self.assertEqual(post1.quote_count, 3)
        self.assertEqual(post1.impression_count, 1000)
        self.assertIsNotNone(post1.posted_at)

        # Verify second post
        post2 = x_posts.get(post_id="9876543210")
        self.assertEqual(post2.text, "Another mention of the paper")
        self.assertEqual(post2.author_id, "654321")
        self.assertEqual(post2.like_count, 25)

    def test_enrich_paper_with_x_updates_existing_posts(self):
        """
        Test that X enrichment updates existing XPost records instead of creating duplicates.
        """
        # Arrange - create an existing XPost
        existing_post = XPost.objects.create(
            paper=self.paper,
            post_id="1234567890",
            text="Old text",
            author_id="123456",
            like_count=10,
            repost_count=2,
            reply_count=1,
            quote_count=0,
            impression_count=100,
        )

        # Response with updated metrics for the same post
        sample_x_response = {
            "post_count": 1,
            "total_likes": 50,
            "total_reposts": 10,
            "total_replies": 5,
            "total_quotes": 3,
            "total_impressions": 1000,
            "terms": [self.paper.doi],
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

        # Verify no duplicate was created
        x_posts = XPost.objects.filter(paper=self.paper)
        self.assertEqual(x_posts.count(), 1)

        # Verify the existing post was updated
        existing_post.refresh_from_db()
        self.assertEqual(existing_post.text, "Great paper on DOI 10.1038/news.2011.490")
        self.assertEqual(existing_post.like_count, 50)
        self.assertEqual(existing_post.repost_count, 10)
        self.assertEqual(existing_post.reply_count, 5)
        self.assertEqual(existing_post.quote_count, 3)
        self.assertEqual(existing_post.impression_count, 1000)

    def test_enrich_paper_with_x_handles_empty_posts_list(self):
        """
        Test that X enrichment handles empty posts list gracefully.
        """
        # Arrange
        sample_x_response = {
            "post_count": 0,
            "total_likes": 0,
            "total_reposts": 0,
            "total_replies": 0,
            "total_quotes": 0,
            "total_impressions": 0,
            "terms": [self.paper.doi],
            "posts": [],
        }
        self.mock_x_client.get_metrics.return_value = sample_x_response

        # Act
        result = self.service.enrich_paper_with_x(self.paper)

        # Assert
        self.assertEqual(result.status, "success")

        # Verify no XPost records were created
        x_posts = XPost.objects.filter(paper=self.paper)
        self.assertEqual(x_posts.count(), 0)
