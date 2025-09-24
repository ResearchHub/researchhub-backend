"""
BioRxiv/MedRxiv base API client for fetching papers.

Handles communication with BioRxiv/MedRxiv API endpoints.
Both repositories share the same API infrastructure.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


class BioRxivBaseConfig(ClientConfig):
    """Base configuration for BioRxiv/MedRxiv API."""

    def __init__(self, **kwargs):
        defaults = {
            "base_url": "https://api.biorxiv.org",  # Same API for both
            "rate_limit": 1.0,  # 1 second timeout per API call recommended
            "page_size": 100,  # API returns 100 papers per page
            "request_timeout": 45.0,  # Longer timeout for large responses
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class BioRxivBaseClient(BaseClient):
    """Base client for fetching papers from BioRxiv and MedRxiv APIs."""

    default_server = "biorxiv"  # Default server, can be overridden in subclasses

    def __init__(self, config: Optional[BioRxivBaseConfig] = None):
        """Initialize base client."""
        if config is None:
            config = BioRxivBaseConfig()
        super().__init__(config)
        self.session = requests.Session()

    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from BioRxiv API.

        Args:
            endpoint: API endpoint (e.g., "/details/biorxiv/2024-01-01/2024-01-31")
            params: Query parameters
            **kwargs: Additional arguments

        Returns:
            JSON response as dict

        Raises:
            FetchError: If request fails
            TimeoutError: If request times out
        """
        url = f"{self.config.base_url}{endpoint}"

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.config.request_timeout,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()

            # BioRxiv returns JSON
            return response.json()

        except requests.Timeout:
            raise TimeoutError(
                f"Request timed out after {self.config.request_timeout}s"
            )
        except requests.RequestException as e:
            raise FetchError(f"Failed to fetch from {url}: {str(e)}")

    def parse(
        self, raw_data: Union[str, bytes, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract collection from BioRxiv API response.

        Minimal processing - just extracts the collection array.
        Full mapping is handled by the mapper.

        Args:
            raw_data: JSON response from API

        Returns:
            List of raw paper records from collection
        """
        if isinstance(raw_data, (str, bytes)):
            raw_data = json.loads(raw_data)

        # BioRxiv response structure:
        # {"messages": [...], "collection": [...]}
        return raw_data.get("collection", [])

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        cursor: int = 0,
        format: str = "json",
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers from BioRxiv within date range.

        Args:
            since: Start date (defaults to 7 days ago)
            until: End date (defaults to today)
            cursor: Pagination cursor (default: 0)
            format: Response format (default: "json")
            **kwargs: Additional parameters

        Returns:
            List of raw paper records
        """
        # Default date range: last 7 days
        if until is None:
            until = datetime.now()
        if since is None:
            since = until - timedelta(days=7)

        # Format dates as YYYY-MM-DD
        since_str = since.strftime("%Y-%m-%d")
        until_str = until.strftime("%Y-%m-%d")

        all_papers = []
        current_cursor = cursor

        while True:
            # BioRxiv API endpoint format:
            # /details/{server}/{interval}/{cursor}/{format}
            # interval is a date range like "2025-01-01/2025-01-31"
            endpoint = f"/details/{self.default_server}/{since_str}/{until_str}/{current_cursor}/{format}"

            logger.info(f"Fetching from {endpoint}")

            try:
                response = self.fetch_with_retry(endpoint)
                papers = self.process_page(response)

                if not papers:
                    # No more results
                    break

                all_papers.extend(papers)

                # Check for pagination
                # BioRxiv returns "messages" with info about total results
                messages = response.get("messages", [])
                if messages:
                    msg = messages[0]
                    # total and count are returned as strings
                    total = int(msg.get("total", "0"))
                    count = int(msg.get("count", "0"))

                    # If we've fetched all results, stop
                    if current_cursor + count >= total:
                        break

                # Move cursor forward
                current_cursor += self.config.page_size

            except Exception as e:
                logger.error(f"Failed to fetch page at cursor {current_cursor}: {e}")
                # Continue with what we have
                break

        logger.info(
            f"Fetched {len(all_papers)} papers from {self.default_server} "
            f"between {since_str} and {until_str}"
        )
        return all_papers
