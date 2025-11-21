import logging
from typing import Dict, List, Optional

import requests
from django.conf import settings

from ..base import RateLimiter

logger = logging.getLogger(__name__)


class BlueSkyClient:
    """
    Client for interacting with the Bluesky API.
    Uses the AT Protocol to search for and retrieve posts mentioning papers.
    Handles authentication, rate limiting, and error handling.
    """

    BASE_URL = "https://bsky.social/xrpc"
    DEFAULT_TIMEOUT = 30
    DEFAULT_RATE_LIMIT = 10.0
    MAX_SEARCH_RESULTS = 100

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ):
        """
        Initialize the Bluesky client.

        Args:
            username: Bluesky username (handle). Defaults to settings.BLUESKY_USERNAME
            password: Bluesky app password. Defaults to settings.BLUESKY_PASSWORD
            timeout: Request timeout in seconds
            rate_limit: Maximum requests per second (default: 10.0)
        """
        self.timeout = timeout
        self.username = (
            username
            if username is not None
            else getattr(settings, "BLUESKY_USERNAME", "")
        )
        self.password = (
            password
            if password is not None
            else getattr(settings, "BLUESKY_PASSWORD", "")
        )
        self.rate_limiter = RateLimiter(rate_limit)
        self.access_token = None
        self.headers = {
            "User-Agent": "ResearchHub/1.0",
            "Accept": "application/json",
        }

    def _authenticate(self) -> bool:
        """
        Authenticate with Bluesky and obtain an access token.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            ValueError: If credentials are not provided
            requests.HTTPError: If authentication request fails
            requests.Timeout: If request times out
            requests.RequestException: For other request errors
        """
        if not self.username or not self.password:
            raise ValueError(
                "Bluesky credentials not provided. "
                "Set BLUESKY_USERNAME and BLUESKY_PASSWORD."
            )

        # Apply rate limiting before making request
        self.rate_limiter.wait_if_needed()

        url = f"{self.BASE_URL}/com.atproto.server.createSession"
        payload = {"identifier": self.username, "password": self.password}

        try:
            response = requests.post(
                url, json=payload, headers=self.headers, timeout=self.timeout
            )

            # Raise for any non-200 status code
            response.raise_for_status()

            data = response.json()
            self.access_token = data.get("accessJwt")
            logger.info("Successfully authenticated with Bluesky")
            return True

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            logger.error(f"Bluesky authentication error. Status: {status}")
            raise
        except requests.Timeout:
            logger.error("Timeout during Bluesky authentication")
            raise
        except requests.RequestException as e:
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

        Raises:
            requests.HTTPError: If search request fails
            requests.Timeout: If request times out
            requests.RequestException: For other request errors
        """
        # Ensure authentication first
        if not self.access_token:
            self._authenticate()

        # Apply rate limiting before making request
        self.rate_limiter.wait_if_needed()

        url = f"{self.BASE_URL}/app.bsky.feed.searchPosts"
        params = {"q": query, "limit": min(limit, self.MAX_SEARCH_RESULTS)}

        headers = self.headers.copy()
        headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=self.timeout
            )

            # Handle token expiration
            if response.status_code == 401:
                logger.warning("Bluesky access token expired, re-authenticating")
                self.access_token = None
                self._authenticate()
                headers["Authorization"] = f"Bearer {self.access_token}"

                # Retry the request with new token
                self.rate_limiter.wait_if_needed()
                response = requests.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )

            # Raise for any non-200 status code
            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            logger.error(f"Bluesky API search error. Status: {status}, query: {query}")
            raise
        except requests.Timeout:
            logger.error(f"Timeout for Bluesky search, query: {query}")
            raise
        except requests.RequestException as e:
            logger.error(f"Bluesky search failed, query: {query}: {str(e)}")
            raise


class BlueSkyMetricsClient:
    """
    Client for retrieving Bluesky metrics for papers.
    """

    def __init__(self, bluesky_client: Optional[BlueSkyClient] = None):
        """
        Constructor.

        Args:
            bluesky_client: Bluesky API client.
                If None, a default client is created using settings credentials.
        """
        self.bluesky_client = bluesky_client or BlueSkyClient()

    def get_metrics(
        self, term: str, limit: int = BlueSkyClient.MAX_SEARCH_RESULTS
    ) -> Optional[Dict]:
        """
        Get Bluesky metrics for a term (DOI, URL, arXiv ID, etc.).

        Args:
            term: The term to search for (e.g., DOI, URL, or arXiv ID)
            limit: Maximum number of posts to retrieve

        Returns:
            Dict containing detailed metrics if successful:
            {
                "post_count": int,
                "total_likes": int,
                "total_reposts": int,
                "total_replies": int,
                "total_quotes": int,
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
        response_data = self.bluesky_client.search_posts(query=term, limit=limit)

        if not response_data:
            logger.warning(f"Failed to retrieve Bluesky metrics for term {term}")
            return None

        posts = response_data.get("posts", [])
        if not posts:
            logger.debug(f"No Bluesky posts found for term: {term}")
            return None

        return self._extract_metrics(posts)

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
            like_count = post.get("likeCount", 0)
            repost_count = post.get("repostCount", 0)
            reply_count = post.get("replyCount", 0)
            quote_count = post.get("quoteCount", 0)

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
                "author_display_name": author.get("displayName"),
                "author_did": author.get("did"),
                "text": record.get("text", ""),
                "created_at": record.get("createdAt"),
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
