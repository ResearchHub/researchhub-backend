"""
Base adapter class for all paper source APIs
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import structlog
from django.conf import settings
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger(__name__)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded"""

    pass


class BaseAdapter(ABC):
    """
    Abstract base class for paper source adapters.

    Each adapter must implement:
    - fetch_recent: Get papers from the last N hours/days
    - fetch_date_range: Get papers between two dates
    - parse_response: Parse raw API response into standard format
    """

    # Override these in subclasses
    SOURCE_NAME = "base"
    DEFAULT_RATE_LIMIT = "10/s"  # Format: "requests/period"
    MAX_RETRIES = 3
    BASE_URL = None

    def __init__(self, rate_limit: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initialize the adapter

        Args:
            rate_limit: Override default rate limit (e.g., "10/s", "100/m")
            api_key: API key if required by the source
        """
        self.rate_limit = rate_limit or self.DEFAULT_RATE_LIMIT
        self.api_key = api_key
        self.last_request_time = None
        self._parse_rate_limit()

        # Configure from settings if available
        ingestion_config = getattr(settings, "INGESTION_CONFIG", {})
        if self.SOURCE_NAME in ingestion_config:
            source_config = ingestion_config[self.SOURCE_NAME]
            self.rate_limit = source_config.get("rate_limit", self.rate_limit)
            self.api_key = source_config.get("api_key", self.api_key)

        logger.info(
            f"Initialized {self.SOURCE_NAME} adapter",
            rate_limit=self.rate_limit,
            has_api_key=bool(self.api_key),
        )

    def _parse_rate_limit(self):
        """Parse rate limit string into requests and period"""
        parts = self.rate_limit.split("/")
        self.requests_per_period = int(parts[0])

        period = parts[1]
        if period.endswith("s"):
            self.period_seconds = float(period[:-1])
        elif period.endswith("m"):
            self.period_seconds = float(period[:-1]) * 60
        elif period.endswith("h"):
            self.period_seconds = float(period[:-1]) * 3600
        else:
            self.period_seconds = 1.0

        # Calculate minimum time between requests
        self.min_time_between_requests = self.period_seconds / self.requests_per_period

    def _enforce_rate_limit(self):
        """Enforce rate limiting between requests"""
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_time_between_requests:
                sleep_time = self.min_time_between_requests - elapsed
                logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f}s")
                time.sleep(sleep_time)

        self.last_request_time = time.time()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def _make_request(self, url: str, params: Optional[Dict] = None) -> Any:
        """
        Make HTTP request with retry logic

        Args:
            url: URL to request
            params: Query parameters

        Returns:
            Response object or parsed data
        """
        import httpx

        self._enforce_rate_limit()

        headers = {}
        if self.api_key:
            headers = self._get_auth_headers()

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise RateLimitExceeded(f"Rate limit exceeded for {self.SOURCE_NAME}")
            raise
        except Exception as e:
            logger.error(
                f"Request failed for {self.SOURCE_NAME}", error=str(e), url=url
            )
            raise

    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers if needed"""
        return {}

    @abstractmethod
    def fetch_recent(self, hours: int = 24) -> Iterator[Dict[str, Any]]:
        """
        Fetch recent papers from the last N hours

        Args:
            hours: Number of hours to look back

        Yields:
            Raw response data for each batch
        """
        pass

    @abstractmethod
    def fetch_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch papers within a date range

        Args:
            start_date: Start of date range
            end_date: End of date range

        Yields:
            Raw response data for each batch
        """
        pass

    @abstractmethod
    def parse_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse raw API response into standard paper format

        Args:
            response_data: Raw response from API

        Returns:
            List of parsed papers with standard fields:
            - title: str
            - abstract: str
            - authors: List[Dict] with 'given', 'family', 'affiliation'
            - published_date: str (ISO format)
            - doi: Optional[str]
            - source_id: str (source-specific identifier)
            - pdf_url: Optional[str]
            - metadata: Dict (source-specific fields)
        """
        pass

    def fetch_by_id(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single paper by its source-specific ID

        Args:
            source_id: Source-specific identifier

        Returns:
            Raw response data or None if not found
        """
        raise NotImplementedError(f"{self.SOURCE_NAME} does not support fetch by ID")

    def validate_response(self, response_data: Dict[str, Any]) -> bool:
        """
        Validate that response contains expected fields

        Args:
            response_data: Response to validate

        Returns:
            True if valid, False otherwise
        """
        # Override in subclasses for source-specific validation
        return bool(response_data)

    def get_total_count(self, response_data: Dict[str, Any]) -> Optional[int]:
        """
        Extract total count of results from response

        Args:
            response_data: API response

        Returns:
            Total count if available, None otherwise
        """
        # Override in subclasses
        return None
