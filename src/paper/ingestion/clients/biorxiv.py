"""
BioRxiv API client for fetching papers.

Handles communication with BioRxiv/MedRxiv API endpoints.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig, CursorState, PagedResponse

logger = logging.getLogger(__name__)


class BioRxivConfig(ClientConfig):
    """BioRxiv-specific configuration."""

    def __init__(self, **kwargs):
        defaults = {
            "source_name": "biorxiv",
            "base_url": "https://api.biorxiv.org",
            "rate_limit": 1.0,  # 1 second timeout per API call recommended
            "page_size": 100,  # BioRxiv returns 100 papers per page
            "request_timeout": 45.0,  # Longer timeout for large responses
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class BioRxivClient(BaseClient):
    """Client for fetching papers from BioRxiv and MedRxiv APIs."""

    def __init__(self, config: Optional[BioRxivConfig] = None):
        """Initialize BioRxiv client."""
        if config is None:
            config = BioRxivConfig()
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

    def fetch_page(
        self,
        cursor: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        page_size: Optional[int] = None,
        server: str = "biorxiv",
        format: str = "json",
        **kwargs,
    ) -> PagedResponse:
        """
        Fetch a single page of BioRxiv results using cursor-based pagination.

        Args:
            cursor: Cursor from previous request (None for first page)
            since: Start date for filtering (used on first request)
            until: End date for filtering (used on first request)
            page_size: Number of results per page
            server: "biorxiv" or "medrxiv" (default: "biorxiv")
            format: Response format (default: "json")
            **kwargs: Additional parameters

        Returns:
            PagedResponse with data and next cursor
        """
        # Parse cursor or initialize state
        if cursor:
            state = CursorState.from_cursor_string(cursor)
            # Restore server from metadata
            server = state.metadata.get("server", server)
            format = state.metadata.get("format", format)
        else:
            # Initialize state for first request
            if until is None:
                until = datetime.now()
            if since is None:
                since = until - timedelta(days=7)

            state = CursorState(
                position=0,
                since=since,
                until=until,
                metadata={"source": "biorxiv", "server": server, "format": format},
            )

        # Use page_size from request or config
        if page_size is None:
            page_size = self.config.page_size

        # Format dates as YYYY-MM-DD
        since_str = state.since.strftime("%Y-%m-%d")
        until_str = state.until.strftime("%Y-%m-%d")

        # BioRxiv API endpoint format:
        # /details/{server}/{interval}/{cursor}/{format}
        endpoint = (
            f"/details/{server}/{since_str}/{until_str}/{state.position}/{format}"
        )

        logger.info(f"Fetching from {endpoint}")

        try:
            response = self.fetch_with_retry(endpoint)
            papers = self.process_page(response)

            # Check for pagination info
            has_more = False
            total = None

            messages = response.get("messages", [])
            if messages:
                msg = messages[0]
                # total and count are returned as strings
                total = int(msg.get("total", "0"))
                count = int(msg.get("count", "0"))

                # Check if there are more results
                has_more = (state.position + count) < total

            # Update state for next page
            next_state = None
            if has_more:
                next_state = CursorState(
                    position=state.position + page_size,
                    since=state.since,
                    until=state.until,
                    total=total,
                    has_more=True,
                    metadata=state.metadata,
                )

            return PagedResponse(
                data=papers,
                cursor=next_state.to_cursor_string() if next_state else None,
                has_more=has_more,
                total=total,
            )

        except Exception as e:
            logger.error(f"Failed to fetch page at cursor {state.position}: {e}")
            raise
