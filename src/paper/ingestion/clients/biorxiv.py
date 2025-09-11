"""
BioRxiv API client for fetching papers.

Handles communication with BioRxiv/MedRxiv API endpoints.
"""

import base64
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Tuple, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


@dataclass
class BioRxivCursor:
    """Cursor for BioRxiv API pagination that encodes date range and position."""

    position: int
    since_date: str  # YYYY-MM-DD format
    until_date: str  # YYYY-MM-DD format
    server: str = "biorxiv"

    def encode(self) -> str:
        """Encode cursor to a base64 string for safe storage/transmission."""
        data = {
            "pos": self.position,
            "since": self.since_date,
            "until": self.until_date,
            "server": self.server,
        }
        json_str = json.dumps(data, separators=(",", ":"))
        encoded = base64.urlsafe_b64encode(json_str.encode()).decode()
        return encoded

    @classmethod
    def decode(cls, encoded_cursor: str) -> "BioRxivCursor":
        """Decode cursor from base64 string."""
        try:
            json_str = base64.urlsafe_b64decode(encoded_cursor.encode()).decode()
            data = json.loads(json_str)
            return cls(
                position=data["pos"],
                since_date=data["since"],
                until_date=data["until"],
                server=data.get("server", "biorxiv"),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise ValueError(f"Invalid cursor format: {e}")

    def __str__(self) -> str:
        """String representation for debugging."""
        return f"BioRxivCursor(pos={self.position}, {self.since_date}→{self.until_date}, {self.server})"


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

    def create_recent_papers_fetcher(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        server: str = "biorxiv",
        start_cursor: Optional[str] = None,
        format: str = "json",
        **kwargs,
    ) -> Callable[[], Tuple[Dict[str, Any], str, bool]]:
        """
        Create a callback function for fetching papers page by page.

        Args:
            since: Start date (defaults to 7 days ago)
            until: End date (defaults to today)
            server: "biorxiv" or "medrxiv" (default: "biorxiv")
            start_cursor: Initial encoded cursor string for resumption (default: None)
            format: Response format (default: "json")
            **kwargs: Additional parameters

        Returns:
            Callable that returns (response, encoded_cursor, has_more)
            - response is the raw API response (unparsed)
            - encoded_cursor is a string that can be stored/transmitted safely

        Raises:
            ValueError: If start_cursor is malformed or has mismatched date range/server
        """
        # Default date range: last 7 days
        if until is None:
            until = datetime.now()
        if since is None:
            since = until - timedelta(days=7)

        # Format dates as YYYY-MM-DD
        since_str = since.strftime("%Y-%m-%d")
        until_str = until.strftime("%Y-%m-%d")

        # Initialize internal cursor
        if start_cursor is None:
            initial_cursor = BioRxivCursor(0, since_str, until_str, server)
        else:
            # Decode the cursor string
            decoded = BioRxivCursor.decode(start_cursor)

            # Validate that cursor matches current date range and server
            if (
                decoded.since_date != since_str
                or decoded.until_date != until_str
                or decoded.server != server
            ):
                raise ValueError(
                    f"Cursor date range mismatch: cursor has {decoded.since_date}→{decoded.until_date} "
                    f"on {decoded.server}, but fetcher expects {since_str}→{until_str} on {server}"
                )
            initial_cursor = decoded

        def fetch_page() -> Tuple[Dict[str, Any], str, bool]:
            """
            Fetch a single page with automatic cursor tracking.

            Returns:
                Tuple of (response, encoded_cursor, has_more)
                - response: Raw API response (unparsed)
                - encoded_cursor: Base64 encoded cursor string for next page
                - has_more: Whether there are more pages available

            Raises:
                FetchError: If request fails
                TimeoutError: If request times out
            """
            current_cursor_obj = fetch_page._current_cursor
            if not fetch_page._has_more:
                # No more pages available - return current cursor
                return {}, current_cursor_obj.encode(), False

            # Use cursor's date range and server (may differ from fetcher defaults if cursor was provided)
            endpoint = (
                f"/details/{current_cursor_obj.server}/{current_cursor_obj.since_date}/"
                f"{current_cursor_obj.until_date}/{current_cursor_obj.position}/{format}"
            )

            response = self.fetch_with_retry(endpoint)

            # Calculate next cursor
            next_position = current_cursor_obj.position
            has_more = False

            messages = response.get("messages", [])
            collection = response.get("collection", [])
            if messages and collection:
                msg = messages[0]
                total = int(msg.get("total", "0"))

                # Calculate next cursor position
                next_position = current_cursor_obj.position + self.config.page_size
                has_more = next_position < total
            else:
                # No pagination info, assume no more pages
                next_position = current_cursor_obj.position + len(collection)
                has_more = False

            # Create next cursor object
            next_cursor_obj = BioRxivCursor(
                position=next_position,
                since_date=current_cursor_obj.since_date,
                until_date=current_cursor_obj.until_date,
                server=current_cursor_obj.server,
            )

            # Update internal state for next automatic call
            fetch_page._current_cursor = next_cursor_obj
            fetch_page._has_more = has_more

            return response, next_cursor_obj.encode(), has_more

        # Internal state for automatic cursor tracking
        fetch_page._current_cursor = initial_cursor
        fetch_page._has_more = True
        return fetch_page
