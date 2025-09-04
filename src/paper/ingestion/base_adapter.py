"""
Base adapter class for paper ingestion from various sources.
"""

import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from .exceptions import FetchError, RetryExhaustedError, TimeoutError, ValidationError

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """Configuration for paper source adapters."""

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


def retry_with_backoff(max_retries: int, initial_backoff: float, max_backoff: float):
    """
    Decorator for retry logic with exponential backoff.

    Exponential backoff means wait time doubles after each failure:
    1st retry: 1 second
    2nd retry: 2 seconds
    3rd retry: 4 seconds (etc.)
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            backoff = initial_backoff

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (FetchError, TimeoutError, ConnectionError) as e:
                    last_exception = e

                    if attempt == max_retries:
                        raise RetryExhaustedError(
                            f"Failed after {max_retries + 1} attempts: {str(e)}",
                            attempts=max_retries + 1,
                        )

                    # Add small random variation to prevent synchronized retries
                    sleep_time = backoff * (0.5 + random.random())

                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries + 1} failed. "
                        f"Retrying in {sleep_time:.1f}s..."
                    )
                    time.sleep(sleep_time)

                    # Double the backoff time for next retry, up to max
                    backoff = min(backoff * 2, max_backoff)

            raise RetryExhaustedError(
                f"Failed after {max_retries + 1} attempts", attempts=max_retries + 1
            )

        return wrapper

    return decorator


class BaseAdapter(ABC):
    """Abstract base class for paper source adapters."""

    def __init__(self, config: AdapterConfig):
        """Initialize the adapter."""
        self.config = config
        self.rate_limiter = RateLimiter(config.rate_limit)

    @abstractmethod
    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from the source API.

        Must be implemented by each source adapter.
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

        Must be implemented by each source adapter.
        """
        pass

    @abstractmethod
    def validate(self, record: Dict[str, Any]) -> bool:
        """
        Validate a parsed record has required fields.

        Must be implemented by each source adapter.
        Returns True if valid, False if should be skipped.
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
        """Fetch data with retry logic."""

        @retry_with_backoff(
            self.config.max_retries,
            self.config.initial_backoff,
            self.config.max_backoff,
        )
        def _fetch():
            return self.fetch_with_rate_limit(endpoint, params, **kwargs)

        return _fetch()

    def process_page(
        self, page_data: Union[str, bytes, Dict[str, Any]], validate: bool = True
    ) -> List[Dict[str, Any]]:
        """Process a page of results."""
        records = self.parse(page_data)

        if validate:
            valid_records = []
            for record in records:
                try:
                    if self.validate(record):
                        valid_records.append(record)
                    else:
                        logger.debug(f"Skipped invalid record: {record.get('id')}")
                except ValidationError as e:
                    logger.error(f"Validation error: {e}")
            return valid_records

        return records

    @abstractmethod
    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """Fetch recent papers within date range."""
        pass

    @abstractmethod
    def fetch_by_id(self, paper_id: str) -> Dict[str, Any]:
        """Fetch a specific paper by ID."""
        pass
