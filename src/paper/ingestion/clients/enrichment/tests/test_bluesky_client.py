from unittest import TestCase
from unittest.mock import Mock, patch

from paper.ingestion.clients.enrichment.bluesky import (
    BlueskyClient,
    BlueskyMetricsClient,
)


class TestBlueskyClient(TestCase):
    """Test suite for the BlueskyClient."""

    def setUp(self):
        """Set up test client."""
        self.mock_atproto_client = Mock()
        self.client = BlueskyClient(
            username="test.bsky.social",
            password="test-password",
            client=self.mock_atproto_client,
        )

    def tearDown(self):
        """Clean up after each test."""
        BlueskyClient._instance = None

    def test_singleton_returns_same_instance(self):
        """Test that BlueskyClient is a singleton."""
        client1 = BlueskyClient()
        client2 = BlueskyClient()

        self.assertIs(client1, client2)

    def test_authenticate_success(self):
        """Test successful authentication."""
        self.assertTrue(self.client.authenticated)
        self.mock_atproto_client.login.assert_called_once_with(
            "test.bsky.social", "test-password"
        )

    def test_authenticate_failure(self):
        """Test authentication failure."""
        self.mock_atproto_client.login.side_effect = Exception("Invalid credentials")

        with self.assertRaises(Exception):
            self.client._authenticate()

    @patch("paper.ingestion.clients.enrichment.bluesky.settings")
    def test_authenticate_no_credentials(self, mock_settings):
        """Test authentication without credentials."""
        # Reset singleton to test fresh initialization
        BlueskyClient._instance = None

        # Mock settings to return empty credentials
        mock_settings.BLUESKY_USERNAME = ""
        mock_settings.BLUESKY_PASSWORD = ""

        with self.assertRaises(ValueError) as context:
            BlueskyClient()

        self.assertIn("credentials not provided", str(context.exception).lower())

    def test_search_posts_success(self):
        """Test successful post search."""
        mock_response = Mock()
        mock_response.model_dump.return_value = {
            "posts": [
                {
                    "uri": "at://did:plc:user1/app.bsky.feed.post/abc123",
                    "cid": "bafyreiabc123",
                    "author": {
                        "did": "did:plc:user1",
                        "handle": "user1.bsky.social",
                        "display_name": "User One",
                    },
                    "record": {
                        "text": "Check out this paper! 10.1038/nature12373",
                        "created_at": "2024-01-15T10:30:00Z",
                    },
                    "like_count": 10,
                    "repost_count": 5,
                    "reply_count": 2,
                    "quote_count": 1,
                }
            ]
        }
        self.mock_atproto_client.app.bsky.feed.search_posts.return_value = mock_response

        result = self.client.search_posts("10.1038/nature12373")

        self.assertIsNotNone(result)
        posts = result.get("posts", [])
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["like_count"], 10)
        self.assertEqual(posts[0]["author"]["handle"], "user1.bsky.social")

    def test_search_posts_not_found(self):
        """Test post search when no posts found (404)."""
        self.mock_atproto_client.app.bsky.feed.search_posts.side_effect = Exception(
            "404 Not Found"
        )

        with self.assertRaises(Exception):
            self.client.search_posts("10.1038/nonexistent")

    def test_search_posts_network_error(self):
        """Test post search with network error."""
        # Set authenticated flag to skip authentication
        self.client.authenticated = True

        self.mock_atproto_client.app.bsky.feed.search_posts.side_effect = Exception(
            "Network error"
        )

        with self.assertRaises(Exception):
            self.client.search_posts("test-query")


class TestBlueskyMetricsClient(TestCase):
    """Test suite for BlueskyMetricsClient."""

    def setUp(self):
        """Set up test client."""
        self.bluesky_client = Mock(spec=BlueskyClient)
        self.metrics_client = BlueskyMetricsClient(bluesky_client=self.bluesky_client)

    def test_extract_metrics_empty_posts(self):
        """Test metrics extraction with empty post list."""
        metrics = BlueskyMetricsClient._extract_metrics([])

        self.assertEqual(metrics["post_count"], 0)
        self.assertEqual(metrics["total_likes"], 0)
        self.assertEqual(metrics["total_reposts"], 0)
        self.assertEqual(metrics["total_replies"], 0)
        self.assertEqual(metrics["total_quotes"], 0)
        self.assertEqual(len(metrics["posts"]), 0)

    def test_extract_metrics_multiple_posts(self):
        """Test metrics extraction with multiple posts."""
        posts = [
            {
                "uri": "at://did:plc:user1/app.bsky.feed.post/abc123",
                "cid": "bafyreiabc123",
                "author": {
                    "did": "did:plc:user1",
                    "handle": "user1.bsky.social",
                    "display_name": "User One",
                },
                "record": {
                    "text": "Great paper!",
                    "created_at": "2024-01-15T10:30:00Z",
                },
                "like_count": 10,
                "repost_count": 5,
                "reply_count": 2,
                "quote_count": 1,
            },
            {
                "uri": "at://did:plc:user2/app.bsky.feed.post/def456",
                "cid": "bafyreidef456",
                "author": {
                    "did": "did:plc:user2",
                    "handle": "user2.bsky.social",
                    "display_name": "User Two",
                },
                "record": {
                    "text": "Interesting findings",
                    "created_at": "2024-01-16T14:20:00Z",
                },
                "like_count": 15,
                "repost_count": 8,
                "reply_count": 3,
                "quote_count": 2,
            },
        ]

        metrics = BlueskyMetricsClient._extract_metrics(posts)

        self.assertEqual(metrics["post_count"], 2)
        self.assertEqual(metrics["total_likes"], 25)
        self.assertEqual(metrics["total_reposts"], 13)
        self.assertEqual(metrics["total_replies"], 5)
        self.assertEqual(metrics["total_quotes"], 3)
        self.assertEqual(len(metrics["posts"]), 2)
        self.assertEqual(metrics["posts"][0]["author_handle"], "user1.bsky.social")

    def test_get_metrics_success(self):
        """Test successful metrics retrieval."""
        self.bluesky_client.search_posts.return_value = {
            "posts": [
                {
                    "uri": "at://test/post/123",
                    "cid": "bafyrei123",
                    "author": {"did": "did:plc:user1", "handle": "user1.bsky.social"},
                    "record": {
                        "text": "Paper link",
                        "created_at": "2024-01-15T10:30:00Z",
                    },
                    "like_count": 10,
                    "repost_count": 5,
                    "reply_count": 2,
                    "quote_count": 1,
                }
            ]
        }

        result = self.metrics_client.get_metrics("10.1038/test")

        self.assertIsNotNone(result)
        self.assertEqual(result["post_count"], 1)
        self.assertEqual(result["total_likes"], 10)
        self.bluesky_client.search_posts.assert_called_once_with(
            query="10.1038/test", limit=100
        )

    def test_get_metrics_no_posts(self):
        """Test metrics retrieval when no posts found."""
        self.bluesky_client.search_posts.return_value = {"posts": []}

        result = self.metrics_client.get_metrics("10.1038/nonexistent")

        self.assertIsNone(result)

    def test_get_metrics_no_response(self):
        """Test metrics retrieval when API returns None."""
        self.bluesky_client.search_posts.return_value = None

        result = self.metrics_client.get_metrics("10.1038/test")

        self.assertIsNone(result)

    def test_get_metrics_with_custom_limit(self):
        """Test metrics retrieval with custom result limit."""
        self.bluesky_client.search_posts.return_value = {"posts": []}

        self.metrics_client.get_metrics("10.1038/test", limit=50)

        self.bluesky_client.search_posts.assert_called_once_with(
            query="10.1038/test", limit=50
        )
