from unittest import TestCase
from unittest.mock import Mock, patch

import requests

from paper.ingestion.clients.enrichment.bluesky import (
    BlueSkyClient,
    BlueSkyMetricsClient,
)


class TestBlueSkyClient(TestCase):
    """Test suite for the BlueSkyClient."""

    def setUp(self):
        """Set up test client."""
        self.client = BlueSkyClient(
            username="test.bsky.social", password="test-password"
        )

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.post")
    def test_authenticate_success(self, mock_post):
        """Test successful authentication."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "accessJwt": "test-access-token",
            "refreshJwt": "test-refresh-token",
            "did": "did:plc:test123",
            "handle": "test.bsky.social",
        }
        mock_post.return_value = mock_response

        result = self.client._authenticate()

        self.assertTrue(result)
        self.assertEqual(self.client.access_token, "test-access-token")

        # Verify the correct URL was called
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        self.assertIn("com.atproto.server.createSession", call_args[0][0])

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.post")
    def test_authenticate_failure(self, mock_post):
        """Test authentication failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Invalid credentials"
        mock_response.raise_for_status.side_effect = requests.HTTPError()
        mock_post.return_value = mock_response

        with self.assertRaises(requests.HTTPError):
            self.client._authenticate()

    def test_authenticate_no_credentials(self):
        """Test authentication without credentials."""
        client = BlueSkyClient(username="", password="")

        with self.assertRaises(ValueError) as context:
            client._authenticate()

        self.assertIn("credentials not provided", str(context.exception).lower())

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.post")
    @patch("paper.ingestion.clients.enrichment.bluesky.requests.get")
    def test_search_posts_success(self, mock_get, mock_post):
        """Test successful post search."""
        # Mock authentication response
        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "accessJwt": "test-token",
            "did": "did:plc:test",
        }
        mock_post.return_value = auth_response

        # Mock search response
        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "posts": [
                {
                    "uri": "at://did:plc:user1/app.bsky.feed.post/abc123",
                    "cid": "bafyreiabc123",
                    "author": {
                        "did": "did:plc:user1",
                        "handle": "user1.bsky.social",
                        "displayName": "User One",
                    },
                    "record": {
                        "text": "Check out this paper! 10.1038/nature12373",
                        "createdAt": "2024-01-15T10:30:00Z",
                    },
                    "likeCount": 10,
                    "repostCount": 5,
                    "replyCount": 2,
                    "quoteCount": 1,
                }
            ]
        }
        mock_get.return_value = search_response

        result = self.client.search_posts("10.1038/nature12373")

        self.assertIsNotNone(result)
        posts = result.get("posts", [])
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["likeCount"], 10)
        self.assertEqual(posts[0]["author"]["handle"], "user1.bsky.social")

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.post")
    @patch("paper.ingestion.clients.enrichment.bluesky.requests.get")
    def test_search_posts_not_found(self, mock_get, mock_post):
        """Test post search when no posts found (404)."""
        # Mock authentication response
        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "accessJwt": "test-token",
            "did": "did:plc:test",
        }
        mock_post.return_value = auth_response

        # Mock search response with 404
        search_response = Mock()
        search_response.status_code = 404
        search_response.raise_for_status.side_effect = requests.HTTPError()
        mock_get.return_value = search_response

        with self.assertRaises(requests.HTTPError):
            self.client.search_posts("10.1038/nonexistent")

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.post")
    @patch("paper.ingestion.clients.enrichment.bluesky.requests.get")
    def test_search_posts_token_expired(self, mock_get, mock_post):
        """Test post search with expired token and re-authentication."""
        # Mock authentication responses
        auth_response = Mock()
        auth_response.status_code = 200
        auth_response.json.return_value = {
            "accessJwt": "test-token",
            "did": "did:plc:test",
        }
        mock_post.return_value = auth_response

        # First search attempt returns 401, second succeeds
        expired_response = Mock()
        expired_response.status_code = 401

        success_response = Mock()
        success_response.status_code = 200
        success_response.json.return_value = {"posts": []}

        mock_get.side_effect = [expired_response, success_response]

        result = self.client.search_posts("test-query")

        # Should have called post twice (initial auth + re-auth)
        self.assertEqual(mock_post.call_count, 2)
        self.assertIsNotNone(result)
        self.assertEqual(len(result.get("posts", [])), 0)

    @patch("paper.ingestion.clients.enrichment.bluesky.requests.get")
    def test_search_posts_network_error(self, mock_get):
        """Test post search with network error."""
        # Set access token to skip authentication
        self.client.access_token = "test-token"

        mock_get.side_effect = requests.RequestException("Network error")

        with self.assertRaises(requests.RequestException):
            self.client.search_posts("test-query")


class TestBlueSkyMetricsClient(TestCase):
    """Test suite for BlueSkyMetricsClient."""

    def setUp(self):
        """Set up test client."""
        self.bluesky_client = Mock(spec=BlueSkyClient)
        self.metrics_client = BlueSkyMetricsClient(bluesky_client=self.bluesky_client)

    def test_extract_metrics_empty_posts(self):
        """Test metrics extraction with empty post list."""
        metrics = BlueSkyMetricsClient._extract_metrics([])

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
                    "displayName": "User One",
                },
                "record": {
                    "text": "Great paper!",
                    "createdAt": "2024-01-15T10:30:00Z",
                },
                "likeCount": 10,
                "repostCount": 5,
                "replyCount": 2,
                "quoteCount": 1,
            },
            {
                "uri": "at://did:plc:user2/app.bsky.feed.post/def456",
                "cid": "bafyreidef456",
                "author": {
                    "did": "did:plc:user2",
                    "handle": "user2.bsky.social",
                    "displayName": "User Two",
                },
                "record": {
                    "text": "Interesting findings",
                    "createdAt": "2024-01-16T14:20:00Z",
                },
                "likeCount": 15,
                "repostCount": 8,
                "replyCount": 3,
                "quoteCount": 2,
            },
        ]

        metrics = BlueSkyMetricsClient._extract_metrics(posts)

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
                        "createdAt": "2024-01-15T10:30:00Z",
                    },
                    "likeCount": 10,
                    "repostCount": 5,
                    "replyCount": 2,
                    "quoteCount": 1,
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
