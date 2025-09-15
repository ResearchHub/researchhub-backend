"""
Base client class for paper source API clients.
"""

import base64
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ..exceptions import FetchError, RetryExhaustedError, TimeoutError

logger = logging.getLogger(__name__)


@dataclass
class CursorState:
    """State for cursor-based pagination."""

    # Common fields for all sources
    position: int  # Current position (offset/skip/start)
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    total: Optional[int] = None  # Total results if known
    has_more: bool = True

    # Source-specific metadata
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_cursor_string(self) -> str:
        """Encode state as an opaque cursor string."""
        data = {
            "position": self.position,
            "since": self.since.isoformat() if self.since else None,
            "until": self.until.isoformat() if self.until else None,
            "total": self.total,
            "has_more": self.has_more,
            "metadata": self.metadata,
        }
        json_str = json.dumps(data, separators=(",", ":"))
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @classmethod
    def from_cursor_string(cls, cursor: str) -> "CursorState":
        """Decode cursor string back to state."""
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            data = json.loads(json_str)
            return cls(
                position=data["position"],
                since=(
                    datetime.fromisoformat(data["since"]) if data["since"] else None
                ),
                until=(
                    datetime.fromisoformat(data["until"]) if data["until"] else None
                ),
                total=data.get("total"),
                has_more=data.get("has_more", True),
                metadata=data.get("metadata", {}),
            )
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"Invalid cursor string: {e}")


@dataclass
class PagedResponse:
    """Response from a paginated API call."""

    data: List[Dict[str, Any]]  # The actual paper records
    cursor: Optional[str] = None  # Cursor for next page (None if no more pages)
    has_more: bool = False  # Whether more pages are available
    total: Optional[int] = None  # Total count if available


@dataclass
class ClientConfig:
    """Configuration for paper source clients."""

    # Source identification
    source_name: str
    base_url: str

    # Rate limiting (requests per second)
    rate_limit: float = 1.0

    # Retry configuration
    max_retries: int = 3
    initial_backoff: float = 1.0  # seconds
    max_backoff: float = 60.0  # seconds

    # Timeout
    request_timeout: float = 30.0  # seconds

    # Pagination
    page_size: int = 100

    # Authentication
    api_key: Optional[str] = None
    auth_token: Optional[str] = None


class RateLimiter:
    """Simple rate limiter - ensures minimum time between requests."""

    def __init__(self, requests_per_second: float):
        self.min_interval = 1.0 / requests_per_second
        self.last_request = 0

    def wait_if_needed(self):
        """Wait if necessary to respect rate limit."""
        now = time.time()
        time_since_last = now - self.last_request
        if time_since_last < self.min_interval:
            sleep_time = self.min_interval - time_since_last
            time.sleep(sleep_time)
        self.last_request = time.time()


class BaseClient(ABC):
    """Abstract base class for paper source API clients."""

    def __init__(self, config: ClientConfig):
        """Initialize the client."""
        self.config = config
        self.rate_limiter = RateLimiter(config.rate_limit)

    @abstractmethod
    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from the source API.

        Must be implemented by each source client.
        Should handle authentication and return raw response.
        """
        pass

    @abstractmethod
    def parse(
        self,
        raw_data: Union[str, bytes, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Parse raw response into list of paper records.

        Must be implemented by each source client.
        This should return minimally processed data.
        """
        pass

    def fetch_with_rate_limit(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """Fetch data with rate limiting."""
        self.rate_limiter.wait_if_needed()
        return self.fetch(endpoint, params, **kwargs)

    def fetch_with_retry(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """Fetch data with retry logic and exponential backoff."""
        backoff = self.config.initial_backoff

        for attempt in range(self.config.max_retries + 1):
            try:
                return self.fetch_with_rate_limit(endpoint, params, **kwargs)
            except (FetchError, TimeoutError, ConnectionError) as e:

                if attempt == self.config.max_retries:
                    raise RetryExhaustedError(
                        f"Failed after {self.config.max_retries + 1} attempts: "
                        f"{str(e)}",
                        attempts=self.config.max_retries + 1,
                    )

                logger.warning(
                    f"Attempt {attempt + 1}/{self.config.max_retries + 1} failed. "
                    f"Retrying in {backoff:.1f}s..."
                )
                time.sleep(backoff)

                # Double the backoff time for next retry, up to max
                backoff = min(backoff * 2, self.config.max_backoff)

        raise RetryExhaustedError(
            f"Failed after {self.config.max_retries + 1} attempts",
            attempts=self.config.max_retries + 1,
        )

    def process_page(
        self, page_data: Union[str, bytes, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process a page of results."""
        return self.parse(page_data)

    @abstractmethod
    def fetch_page(
        self,
        cursor: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        page_size: Optional[int] = None,
        **kwargs,
    ) -> PagedResponse:
        """
        Fetch a single page of results using cursor-based pagination.

        Args:
            cursor: Cursor from previous request (None for first page)
            since: Start date for filtering (used on first request)
            until: End date for filtering (used on first request)
            page_size: Number of results per page
            **kwargs: Additional source-specific parameters

        Returns:
            PagedResponse with data and next cursor
        """
        pass

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers within date range.

        This is a convenience method that fetches all pages automatically.
        For more control, use fetch_page directly.

        Args:
            since: Start date
            until: End date
            max_results: Maximum number of results to return
            **kwargs: Additional parameters

        Returns:
            List of all paper records
        """
        all_papers = []
        cursor = None
        first_page = True

        while True:
            # Only pass dates on first request
            if first_page:
                response = self.fetch_page(
                    cursor=cursor,
                    since=since,
                    until=until,
                    page_size=self.config.page_size,
                    **kwargs,
                )
                first_page = False
            else:
                response = self.fetch_page(cursor=cursor, **kwargs)

            all_papers.extend(response.data)

            # Check if we've reached the desired number of results
            if max_results and len(all_papers) >= max_results:
                all_papers = all_papers[:max_results]
                break

            # Check if there are more pages
            if not response.has_more or response.cursor is None:
                break

            cursor = response.cursor

        return all_papers
