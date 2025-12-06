import logging
from typing import Dict, List, Optional

from django.conf import settings
from xdk import Client

from ..base import RateLimiter

logger = logging.getLogger(__name__)


class XClient:
    """
    Client for interacting with the X (Twitter) API.
    Uses the X SDK to search for and retrieve posts mentioning papers.
    Handles authentication, rate limiting, and error handling.

    This class is a singleton - all instantiations return the same instance.
    """

    DEFAULT_RATE_LIMIT = 1.0  # X API has stricter rate limits
    MAX_SEARCH_RESULTS = 100

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        bearer_token: Optional[str] = None,
        client=None,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ):
        """
        Initialize the X client.

        Args:
            bearer_token: X API Bearer Token. Defaults to settings.X_BEARER_TOKEN
            client: X SDK Client instance. If None, creates a new Client()
            rate_limit: Maximum requests per second (default: 1.0)
        """
        if self._initialized:
            return
        self._initialized = True

        self.bearer_token = bearer_token or getattr(settings, "X_BEARER_TOKEN", "")
        self.rate_limiter = RateLimiter(rate_limit)
        self._client = client
        self._init_client()

    def _init_client(self):
        """
        Initialize the X SDK client with bearer token.

        Raises:
            ValueError: If bearer token is not provided
        """
        if not self.bearer_token:
            raise ValueError(
                "X API bearer token not provided. " "Set X_BEARER_TOKEN in settings."
            )

        if self._client is None:
            self._client = Client(bearer_token=self.bearer_token)

        logger.info("X client initialized successfully")

    def search_posts(self, query: str, max_results: int = 10) -> Optional[Dict]:
        """
        Search for recent posts on X matching a query (last 7 days).

        Args:
            query: Search query string
            max_results: Maximum number of results to return (max 100)

        Returns:
            Response dict if successful, None if error occurred
        """
        # Apply rate limiting before making request
        self.rate_limiter.wait_if_needed()

        try:
            # Limit max_results to API maximum
            max_results = min(max_results, self.MAX_SEARCH_RESULTS)

            all_posts = []
            for page in self._client.posts.search_all(
                query=query,
                max_results=max_results,
                tweet_fields=["public_metrics", "created_at", "author_id"],
            ):
                if hasattr(page, "data") and page.data:
                    all_posts.extend(page.data)
                # Only fetch first page to respect max_results
                break

            if all_posts:
                return {
                    "posts": [self._parse_post(post) for post in all_posts],
                    "meta": {},
                }
            return {"posts": [], "meta": {}}

        except Exception as e:
            logger.error(f"X API search error: {str(e)}")
            raise

    def _parse_post(self, post) -> Dict:
        """
        Parse a post object from the X API response.

        Args:
            post: Post object from X API

        Returns:
            Parsed post dictionary
        """
        # Handle both dict and object responses
        if isinstance(post, dict):
            post_id = post.get("id")
            text = post.get("text", "")
            author_id = post.get("author_id")
            created_at = post.get("created_at")
            public_metrics = post.get("public_metrics", {})
        else:
            post_id = getattr(post, "id", None)
            text = getattr(post, "text", "")
            author_id = getattr(post, "author_id", None)
            created_at = getattr(post, "created_at", None)
            public_metrics = getattr(post, "public_metrics", {}) or {}

        return {
            "id": post_id,
            "text": text,
            "author_id": author_id,
            "created_at": str(created_at) if created_at else None,
            "like_count": public_metrics.get("like_count", 0),
            "repost_count": public_metrics.get("retweet_count", 0),
            "reply_count": public_metrics.get("reply_count", 0),
            "quote_count": public_metrics.get("quote_count", 0),
            "impression_count": public_metrics.get("impression_count", 0),
        }


class XMetricsClient:
    """
    Client for retrieving X metrics for papers.
    """

    def __init__(self, x_client: Optional[XClient] = None):
        """
        Constructor.

        Args:
            x_client: X API client.
                If None, creates an XClient (which is a singleton).
        """
        self.x_client = x_client or XClient()

    def get_metrics(
        self, term: str, max_results: int = XClient.MAX_SEARCH_RESULTS
    ) -> Optional[Dict]:
        """
        Get X metrics for a term (DOI, URL, arXiv ID, etc.).

        Args:
            term: The term to search for (e.g., DOI, URL, or arXiv ID)
            max_results: Maximum number of posts to retrieve

        Returns:
            Dict containing detailed metrics if successful:
            {
                "post_count": int,
                "total_likes": int,
                "total_reposts": int,
                "total_replies": int,
                "total_quotes": int,
                "total_impressions": int,
                "posts": [
                    {
                        "id": str,
                        "text": str,
                        "author_id": str,
                        "created_at": str,
                        "like_count": int,
                        "repost_count": int,
                        "reply_count": int,
                        "quote_count": int,
                        "impression_count": int
                    },
                    ...
                ]
            }
            None if error occurred
        """
        try:
            response_data = self.x_client.search_posts(
                query=term, max_results=max_results
            )
        except Exception as e:
            logger.error(f"Error retrieving X metrics for term {term}: {str(e)}")
            return None

        if not response_data:
            logger.warning(f"Failed to retrieve X metrics for term {term}")
            return None

        posts = response_data.get("posts", [])
        if not posts:
            logger.debug(f"No X posts found for term: {term}")
            return None

        return self._extract_metrics(posts)

    @staticmethod
    def _extract_metrics(posts: List[Dict]) -> Dict:
        """
        Extract aggregated metrics from a list of posts.

        Args:
            posts: List of post dictionaries from X API

        Returns:
            Dictionary with aggregated metrics
        """
        if not posts:
            return {
                "post_count": 0,
                "total_likes": 0,
                "total_reposts": 0,
                "total_replies": 0,
                "total_quotes": 0,
                "total_impressions": 0,
                "posts": [],
            }

        total_likes = 0
        total_reposts = 0
        total_replies = 0
        total_quotes = 0
        total_impressions = 0

        for post in posts:
            total_likes += post.get("like_count", 0)
            total_reposts += post.get("repost_count", 0)
            total_replies += post.get("reply_count", 0)
            total_quotes += post.get("quote_count", 0)
            total_impressions += post.get("impression_count", 0)

        return {
            "post_count": len(posts),
            "total_likes": total_likes,
            "total_reposts": total_reposts,
            "total_replies": total_replies,
            "total_quotes": total_quotes,
            "total_impressions": total_impressions,
            "posts": posts,
        }
