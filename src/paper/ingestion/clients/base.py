"""
Base client class for paper source API clients.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from ..exceptions import FetchError, RetryExhaustedError, TimeoutError

logger = logging.getLogger(__name__)


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
    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Fetch recent papers within date range."""
        pass
