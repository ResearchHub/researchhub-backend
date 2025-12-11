import logging
from typing import Dict, List, Optional

from atproto import Client
from django.conf import settings

from ..base import RateLimiter

logger = logging.getLogger(__name__)


class BlueskyClient:
    """
    Client for interacting with the Bluesky API.
    Uses the AT Protocol to search for and retrieve posts mentioning papers.
    Handles authentication, rate limiting, and error handling.

    This class is a singleton - all instantiations return the same instance.
    """

    DEFAULT_RATE_LIMIT = 10.0
    MAX_SEARCH_RESULTS = 100

    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        client: Optional[Client] = None,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ):
        """
        Initialize the Bluesky client.

        Args:
            username: Bluesky username (handle). Defaults to settings.BLUESKY_USERNAME
            password: Bluesky app password. Defaults to settings.BLUESKY_PASSWORD
            client: AT Protocol client instance. If None, creates a new Client()
            rate_limit: Maximum requests per second (default: 10.0)
        """
        if self._initialized:
            return
        self._initialized = True

        self.username = username or getattr(settings, "BLUESKY_USERNAME", "")
        self.password = password or getattr(settings, "BLUESKY_PASSWORD", "")
        self.rate_limiter = RateLimiter(rate_limit)
        self.client = client or Client()
        self.authenticated = False
        self._authenticate()

    def _authenticate(self):
        """
        Authenticate with Bluesky and obtain an access token.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            ValueError: If credentials are not provided
            Exception: If authentication fails
        """
        if not self.username or not self.password:
            raise ValueError(
                "Bluesky credentials not provided. "
                "Set BLUESKY_USERNAME and BLUESKY_PASSWORD."
            )

        self.rate_limiter.wait_if_needed()

        try:
            self.client.login(self.username, self.password)
            self.authenticated = True
            logger.info("Successfully authenticated with Bluesky")

        except Exception as e:
            logger.error(f"Bluesky authentication failed: {str(e)}")
            raise

    def search_posts(
        self, query: str, limit: int = MAX_SEARCH_RESULTS
    ) -> Optional[Dict]:
        """
        Search for posts on Bluesky matching a query.

        Args:
            query: Search query string
            limit: Maximum number of results to return

        Returns:
            Response JSON dict if successful, None if error occurred
        """
        if not self.authenticated:
            self._authenticate()

        # Apply rate limiting before making request
        self.rate_limiter.wait_if_needed()

        # Note: The SDK automatically refreshes expired access tokens
        response = self.client.app.bsky.feed.search_posts(
            params={"q": query, "limit": min(limit, self.MAX_SEARCH_RESULTS)}
        )

        return response.model_dump() if hasattr(response, "model_dump") else response


class BlueskyMetricsClient:
    """
    Client for retrieving Bluesky metrics for papers.
    """

    def __init__(self, bluesky_client: Optional[BlueskyClient] = None):
        """
        Constructor.

        Args:
            bluesky_client: Bluesky API client.
                If None, creates a BlueskyClient (which is a singleton).
        """
        self.bluesky_client = bluesky_client or BlueskyClient()

    def get_metrics(
        self, terms: List[str], limit: int = BlueskyClient.MAX_SEARCH_RESULTS
    ) -> Optional[Dict]:
        """
        Get Bluesky metrics for a list of terms (DOI, title, etc.).

        Searches for each term separately and deduplicates results by post URI.

        Args:
            terms: List of terms to search for (e.g., DOI and/or paper title).
            limit: Maximum number of posts to retrieve per term

        Returns:
            Dict containing detailed metrics if successful:
            {
                "post_count": int,
                "total_likes": int,
                "total_reposts": int,
                "total_replies": int,
                "total_quotes": int,
                "terms": list[str],
                "posts": [
                    {
                        "uri": str,
                        "cid": str,
                        "author_handle": str,
                        "author_display_name": str,
                        "author_did": str,
                        "text": str,
                        "created_at": str,
                        "like_count": int,
                        "repost_count": int,
                        "reply_count": int,
                        "quote_count": int
                    },
                    ...
                ]
            }
            None if error occurred
        """
        # Filter out empty terms
        terms = [t for t in terms if t]
        if not terms:
            logger.warning("No valid terms provided for Bluesky search")
            return None

        # Collect posts from all terms, deduplicated by URI
        all_posts: Dict[str, Dict] = {}

        for term in terms:
            try:
                response_data = self.bluesky_client.search_posts(
                    query=term, limit=limit
                )
            except Exception as e:
                logger.error(
                    f"Error retrieving Bluesky metrics for term {term}: {str(e)}"
                )
                continue

            if not response_data:
                logger.debug(f"No response for Bluesky term: {term}")
                continue

            posts = response_data.get("posts", [])
            for post in posts:
                uri = post.get("uri")
                if uri and uri not in all_posts:
                    all_posts[uri] = post

        if not all_posts:
            logger.debug(f"No Bluesky posts found for terms: {terms}")
            return None

        metrics = self._extract_metrics(list(all_posts.values()))
        metrics["terms"] = terms
        return metrics

    @staticmethod
    def _extract_metrics(posts: List[Dict]) -> Dict:
        """
        Extract aggregated metrics from a list of posts.

        Args:
            posts: List of post dictionaries from Bluesky API

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
                "posts": [],
            }

        total_likes = 0
        total_reposts = 0
        total_replies = 0
        total_quotes = 0
        post_summaries = []

        for post in posts:
            # Extract engagement metrics
            like_count = post.get("like_count", 0)
            repost_count = post.get("repost_count", 0)
            reply_count = post.get("reply_count", 0)
            quote_count = post.get("quote_count", 0)

            total_likes += like_count
            total_reposts += repost_count
            total_replies += reply_count
            total_quotes += quote_count

            # Extract post details
            author = post.get("author", {})
            record = post.get("record", {})

            post_summary = {
                "uri": post.get("uri"),
                "cid": post.get("cid"),
                "author_handle": author.get("handle"),
                "author_display_name": author.get("display_name"),
                "author_did": author.get("did"),
                "text": record.get("text", ""),
                "created_at": record.get("created_at"),
                "like_count": like_count,
                "repost_count": repost_count,
                "reply_count": reply_count,
                "quote_count": quote_count,
            }
            post_summaries.append(post_summary)

        return {
            "post_count": len(posts),
            "total_likes": total_likes,
            "total_reposts": total_reposts,
            "total_replies": total_replies,
            "total_quotes": total_quotes,
            "posts": post_summaries,
        }
