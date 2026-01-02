from unittest import TestCase
from unittest.mock import Mock, patch

from paper.ingestion.clients.enrichment.x import XClient


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

    @patch("paper.ingestion.clients.enrichment.x.settings.X_BEARER_TOKEN", None)
    def test_init_no_bearer_token(self):
        """Test initialization without bearer token."""
        # Reset singleton to test fresh initialization
        XClient._instance = None

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

        result = self.client.search_posts(["10.1038/nature12373"])

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["like_count"], 10)
        self.assertEqual(result[0]["repost_count"], 5)
        self.assertEqual(result[0]["id"], "1234567890")
        mock_rate_limiter.assert_called_once()

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_no_results(self, mock_rate_limiter):
        """Test post search when no posts found."""
        mock_page = Mock()
        mock_page.data = None
        self.mock_xdk_client.posts.search_all.return_value = iter([mock_page])

        result = self.client.search_posts(["10.1038/nonexistent"])

        self.assertIsNotNone(result)
        self.assertEqual(result, [])

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_api_error(self, mock_rate_limiter):
        """Test post search with API error."""
        self.mock_xdk_client.posts.search_all.side_effect = Exception(
            "401 Unauthorized"
        )

        with self.assertRaises(Exception):
            self.client.search_posts(["test-query"])

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_rate_limit_error(self, mock_rate_limiter):
        """Test post search with rate limit error."""
        self.mock_xdk_client.posts.search_all.side_effect = Exception(
            "429 Too Many Requests"
        )

        with self.assertRaises(Exception):
            self.client.search_posts(["test-query"])

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

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_with_multiple_terms(self, mock_rate_limiter):
        """Test search with multiple terms uses OR logic."""
        mock_page = Mock()
        mock_page.data = []
        self.mock_xdk_client.posts.search_all.return_value = iter([mock_page])

        self.client.search_posts(["10.1038/test", "A Novel Machine Learning Approach"])

        # Verify OR logic is used in the query
        call_args = self.mock_xdk_client.posts.search_all.call_args
        query = call_args.kwargs["query"]
        self.assertIn('"10.1038/test"', query)
        self.assertIn('"A Novel Machine Learning Approach"', query)
        self.assertIn(" OR ", query)

    @patch("paper.ingestion.clients.enrichment.x.RateLimiter.wait_if_needed")
    def test_search_posts_with_bot_filtering(self, mock_rate_limiter):
        """Test search with bot account filtering."""
        mock_page = Mock()
        mock_page.data = []
        self.mock_xdk_client.posts.search_all.return_value = iter([mock_page])

        self.client.search_posts(
            ["10.1038/test"],
            external_source="biorxiv",
            hub_slugs=["neuroscience"],
        )

        # Verify the query includes bot exclusions
        call_args = self.mock_xdk_client.posts.search_all.call_args
        query = call_args.kwargs["query"]
        self.assertIn("-from:", query)
        self.assertIn("10.1038/test", query)

    def test_search_posts_empty_terms_returns_none(self):
        """Test search with empty terms returns None."""
        result = self.client.search_posts([])

        self.assertIsNone(result)
