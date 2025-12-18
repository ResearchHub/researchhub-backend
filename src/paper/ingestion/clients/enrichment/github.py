import logging
from typing import Dict, Optional

import requests

from ..base import RateLimiter

logger = logging.getLogger(__name__)


class GithubClient:
    """
    GitHub API client.
    Handles authentication, rate limiting, and error handling.
    """

    BASE_URL = "https://api.github.com"
    DEFAULT_TIMEOUT = 10
    # See: https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
    DEFAULT_RATE_LIMIT = 1 / 6

    def __init__(
        self,
        api_token: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        rate_limit: float = DEFAULT_RATE_LIMIT,
    ):
        """
        Constructor.

        Args:
            api_token: GitHub API token (optional, needed for higher rate limits).
            timeout: Request timeout in seconds.
            rate_limit: Maximum requests per second (default: 10.0).
        """
        self.api_token = api_token
        self.timeout = timeout
        self.rate_limiter = RateLimiter(rate_limit)

        # Mandatory headers for GitHub API
        # See: https://docs.github.com/en/rest/using-the-rest-api/getting-started-with-the-rest-api#headers
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ResearchHub/1.0",
        }
        if self.api_token:
            self.headers["Authorization"] = f"Bearer {self.api_token}"

    def search(
        self,
        endpoint: str,
        query: str,
        per_page: int = 1,
    ) -> Optional[Dict]:
        """
        Execute a search request against GitHub's search API.

        Args:
            endpoint: Search endpoint (e.g., "code", "issues")
            query: Search query string
            per_page: Number of results per page

        Returns:
            Response JSON dict if successful, None if error occurred
        """
        # Apply rate limiting before making request
        self.rate_limiter.wait_if_needed()

        url = f"{self.BASE_URL}/search/{endpoint}"
        params = {"q": query, "per_page": per_page}

        try:
            response = requests.get(
                url, headers=self.headers, params=params, timeout=self.timeout
            )

            # Raise for any non-200 status code
            response.raise_for_status()
            return response.json()

        except requests.HTTPError as e:
            logger.warning(
                f"GitHub API {endpoint} search error. "
                f"Status: {e.response.status_code}, query: {query}"
            )
            raise
        except requests.Timeout:
            logger.warning(f"Timeout for GitHub {endpoint} search, query: {query}")
            raise
        except requests.RequestException as e:
            logger.warning(f"GitHub {endpoint} search failed, query: {query}: {str(e)}")
            raise


class GithubMetricsClient:
    """
    Client for retrieving mentions of a given term in Github.
    """

    VALID_SEARCH_AREAS = ["code", "issues", "commits", "repositories"]
    DEFAULT_SEARCH_AREAS = ["issues", "commits", "repositories"]

    def __init__(self, github_client: Optional[GithubClient] = None):
        """
        Constructor.

        Args:
            github_client: Github API client.
                           If None, an unauthenticated default client is created.
        """
        self.github_client = github_client or GithubClient()

    def get_mentions(
        self, terms: list[str], search_areas: Optional[list] = None
    ) -> Optional[Dict]:
        """
        Get mentions of terms on GitHub using OR logic.

        Args:
            terms: List of terms to search for (e.g., DOI and/or paper title).
                   Multiple terms are combined with OR logic.
            search_areas: List of areas to search. If None, uses default areas.

        Returns:
            Dict containing detailed metrics if successful:
            {
                "total_mentions": int,
                "terms": list[str],
                "breakdown": {
                    "code": int,
                    "issues": int,
                    "commits": int,
                    "repositories": int
                }
            }
            None if error occurred
        """
        search_areas = search_areas or self.DEFAULT_SEARCH_AREAS
        breakdown = {}

        # Build query with OR logic for multiple terms
        query = self._build_query(terms)

        for area in search_areas:
            count = self._search_area(query, area)
            if count is not None:
                breakdown[area] = count
                logger.debug(f"Found {count} mentions in {area} for query {query}")
            else:
                logger.warning(f"Failed to search {area} for query {query}")

        if not breakdown:
            logger.warning(f"Failed to retrieve GitHub mention count for query {query}")
            return None

        total_mentions = sum(breakdown.values())
        logger.info(
            f"Found {total_mentions} total mentions for query {query}. "
            f"Breakdown: {breakdown}"
        )

        return {
            "total_mentions": total_mentions,
            "terms": terms,
            "breakdown": breakdown,
        }

    def _build_query(self, terms: list[str]) -> str:
        """
        Build a GitHub search query from a list of terms using OR logic.

        Each term is quoted to ensure exact phrase matching.

        Args:
            terms: List of terms to combine with OR.

        Returns:
            GitHub search query string.
        """
        # Quote each term and join with OR
        quoted_terms = [f'"{term}"' for term in terms if term]
        return " OR ".join(quoted_terms)

    def _search_area(self, query: str, area: str) -> Optional[int]:
        """
        Search a specific GitHub area for mentions.

        Args:
            query: The search query string.
            area: Area to search ("code", "issues", "commits", "repositories")

        Returns:
            Count of mentions in that area, None if error occurred

        Raises:
            ValueError: If area is not a valid search area
        """
        if area not in self.VALID_SEARCH_AREAS:
            raise ValueError(f"Invalid search area: {area}. ")

        # https://docs.github.com/en/rest/search/search?apiVersion=2022-11-28#search-issues-and-pull-requests
        # We need to specify `is:issue` to search only issues, otherwise we get a 422.
        if area == "issues":
            query = f"{query} is:issue"

        response_data = self.github_client.search(
            endpoint=area,
            query=query,
            per_page=1,
        )

        return response_data.get("total_count", 0) if response_data else None
