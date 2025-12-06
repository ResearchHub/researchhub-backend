from unittest import TestCase
from unittest.mock import Mock, patch

from paper.ingestion.clients.enrichment.x import XClient, XMetricsClient


class TestXClient(TestCase):
    """Test suite for the XClient."""

    def setUp(self):
        """Set up test client."""
        self.mock_xdk_client = Mock()
        self.client = XClient(
            bearer_token="test-bearer-token",
            client=self.mock_xdk_client,
        )

    def tearDown(self):
        """Clean up after each test."""
        XClient._instance = None

    def test_singleton_returns_same_instance(self):
        """Test that XClient is a singleton."""
        client1 = XClient()
        client2 = XClient()

        self.assertIs(client1, client2)

    @patch("paper.ingestion.clients.enrichment.x.settings")
    def test_init_no_bearer_token(self, mock_settings):
        """Test initialization without bearer token."""
        # Reset singleton to test fresh initialization
        XClient._instance = None

        # Mock settings to return empty token
        mock_settings.X_BEARER_TOKEN = ""

        with self.assertRaises(ValueError) as context:
            XClient()

        self.assertIn("bearer token not provided", str(context.exception).lower())

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_success(self, mock_rate_limiter):
        """Test successful post search."""
        mock_page = Mock()
        mock_page.data = [
            {
                "id": "1234567890",
                "text": "Check out this paper! 10.1038/nature12373",
                "author_id": "user123",
                "created_at": "2024-01-15T10:30:00Z",
                "public_metrics": {
                    "like_count": 10,
                    "retweet_count": 5,
                    "reply_count": 2,
                    "quote_count": 1,
                    "impression_count": 100,
                },
            }
        ]
        # Mock the generator to yield a single page
        self.mock_xdk_client.posts.search_all.return_value = iter([mock_page])

        result = self.client.search_posts("10.1038/nature12373")

        self.assertIsNotNone(result)
        posts = result.get("posts", [])
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["like_count"], 10)
        self.assertEqual(posts[0]["repost_count"], 5)
        self.assertEqual(posts[0]["id"], "1234567890")
        mock_rate_limiter.assert_called_once()

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_no_results(self, mock_rate_limiter):
        """Test post search when no posts found."""
        mock_page = Mock()
        mock_page.data = None
        self.mock_xdk_client.posts.search_all.return_value = iter([mock_page])

        result = self.client.search_posts("10.1038/nonexistent")

        self.assertIsNotNone(result)
        self.assertEqual(result["posts"], [])

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_api_error(self, mock_rate_limiter):
        """Test post search with API error."""
        self.mock_xdk_client.posts.search_all.side_effect = Exception(
            "401 Unauthorized"
        )

        with self.assertRaises(Exception):
            self.client.search_posts("test-query")

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_rate_limit_error(self, mock_rate_limiter):
        """Test post search with rate limit error."""
        self.mock_xdk_client.posts.search_all.side_effect = Exception(
            "429 Too Many Requests"
        )

        with self.assertRaises(Exception):
            self.client.search_posts("test-query")

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_parse_post_dict_format(self, mock_rate_limiter):
        """Test parsing post in dictionary format."""
        post = {
            "id": "123",
            "text": "Test post",
            "author_id": "user1",
            "created_at": "2024-01-15T10:00:00Z",
            "public_metrics": {
                "like_count": 5,
                "retweet_count": 3,
                "reply_count": 1,
                "quote_count": 0,
                "impression_count": 50,
            },
        }

        result = self.client._parse_post(post)

        self.assertEqual(result["id"], "123")
        self.assertEqual(result["text"], "Test post")
        self.assertEqual(result["like_count"], 5)
        self.assertEqual(result["repost_count"], 3)
        self.assertEqual(result["impression_count"], 50)

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_parse_post_object_format(self, mock_rate_limiter):
        """Test parsing post in object format."""
        post = Mock()
        post.id = "456"
        post.text = "Object post"
        post.author_id = "user2"
        post.created_at = "2024-01-16T12:00:00Z"
        post.public_metrics = {
            "like_count": 10,
            "retweet_count": 8,
            "reply_count": 2,
            "quote_count": 1,
            "impression_count": 200,
        }

        result = self.client._parse_post(post)

        self.assertEqual(result["id"], "456")
        self.assertEqual(result["text"], "Object post")
        self.assertEqual(result["like_count"], 10)
        self.assertEqual(result["repost_count"], 8)


class TestXMetricsClient(TestCase):
    """Test suite for XMetricsClient."""

    def setUp(self):
        """Set up test client."""
        self.x_client = Mock(spec=XClient)
        self.metrics_client = XMetricsClient(x_client=self.x_client)

    def test_extract_metrics_empty_posts(self):
        """Test metrics extraction with empty post list."""
        metrics = XMetricsClient._extract_metrics([])

        self.assertEqual(metrics["post_count"], 0)
        self.assertEqual(metrics["total_likes"], 0)
        self.assertEqual(metrics["total_reposts"], 0)
        self.assertEqual(metrics["total_replies"], 0)
        self.assertEqual(metrics["total_quotes"], 0)
        self.assertEqual(metrics["total_impressions"], 0)
        self.assertEqual(len(metrics["posts"]), 0)

    def test_extract_metrics_multiple_posts(self):
        """Test metrics extraction with multiple posts."""
        posts = [
            {
                "id": "123",
                "text": "Great paper!",
                "author_id": "user1",
                "created_at": "2024-01-15T10:30:00Z",
                "like_count": 10,
                "repost_count": 5,
                "reply_count": 2,
                "quote_count": 1,
                "impression_count": 100,
            },
            {
                "id": "456",
                "text": "Interesting findings",
                "author_id": "user2",
                "created_at": "2024-01-16T14:20:00Z",
                "like_count": 15,
                "repost_count": 8,
                "reply_count": 3,
                "quote_count": 2,
                "impression_count": 150,
            },
        ]

        metrics = XMetricsClient._extract_metrics(posts)

        self.assertEqual(metrics["post_count"], 2)
        self.assertEqual(metrics["total_likes"], 25)
        self.assertEqual(metrics["total_reposts"], 13)
        self.assertEqual(metrics["total_replies"], 5)
        self.assertEqual(metrics["total_quotes"], 3)
        self.assertEqual(metrics["total_impressions"], 250)
        self.assertEqual(len(metrics["posts"]), 2)

    def test_get_metrics_success(self):
        """Test successful metrics retrieval."""
        self.x_client.search_posts.return_value = {
            "posts": [
                {
                    "id": "123",
                    "text": "Paper link",
                    "author_id": "user1",
                    "created_at": "2024-01-15T10:30:00Z",
                    "like_count": 10,
                    "repost_count": 5,
                    "reply_count": 2,
                    "quote_count": 1,
                    "impression_count": 100,
                }
            ]
        }

        result = self.metrics_client.get_metrics("10.1038/test")

        self.assertIsNotNone(result)
        self.assertEqual(result["post_count"], 1)
        self.assertEqual(result["total_likes"], 10)
        self.assertEqual(result["total_impressions"], 100)
        self.x_client.search_posts.assert_called_once_with(
            query="10.1038/test", max_results=100
        )

    def test_get_metrics_no_posts(self):
        """Test metrics retrieval when no posts found."""
        self.x_client.search_posts.return_value = {"posts": []}

        result = self.metrics_client.get_metrics("10.1038/nonexistent")

        self.assertIsNone(result)

    def test_get_metrics_no_response(self):
        """Test metrics retrieval when API returns None."""
        self.x_client.search_posts.return_value = None

        result = self.metrics_client.get_metrics("10.1038/test")

        self.assertIsNone(result)

    def test_get_metrics_api_error(self):
        """Test metrics retrieval when API raises exception."""
        self.x_client.search_posts.side_effect = Exception("API Error")

        result = self.metrics_client.get_metrics("10.1038/test")

        self.assertIsNone(result)

    def test_get_metrics_with_custom_limit(self):
        """Test metrics retrieval with custom result limit."""
        self.x_client.search_posts.return_value = {"posts": []}

        self.metrics_client.get_metrics("10.1038/test", max_results=50)

        self.x_client.search_posts.assert_called_once_with(
            query="10.1038/test", max_results=50
        )
