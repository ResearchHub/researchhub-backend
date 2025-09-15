"""
ChemRxiv API client for fetching chemistry preprints.

Handles communication with ChemRxiv Engage API endpoints.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig, CursorState, PagedResponse

logger = logging.getLogger(__name__)


class ChemRxivConfig(ClientConfig):
    """ChemRxiv-specific configuration."""

    def __init__(self, **kwargs):
        # Extract ChemRxiv-specific config
        self.max_results_per_query = kwargs.pop("max_results_per_query", 1000)

        defaults = {
            "source_name": "chemrxiv",
            "base_url": "https://chemrxiv.org/engage/chemrxiv/public-api/v1",
            "rate_limit": 1.0,  # 1 request per second (conservative default)
            "page_size": 100,
            "request_timeout": 30.0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class ChemRxivClient(BaseClient):
    """Client for fetching papers from ChemRxiv Engage API."""

    def __init__(self, config: Optional[ChemRxivConfig] = None):
        """Initialize ChemRxiv client."""
        if config is None:
            config = ChemRxivConfig()
        super().__init__(config)
        self.session = requests.Session()

    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from ChemRxiv API.

        Args:
            endpoint: API endpoint (e.g., "/items")
            params: Query parameters
            **kwargs: Additional arguments

        Returns:
            JSON response as dictionary

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

            # ChemRxiv returns JSON
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
        Parse ChemRxiv JSON response and return raw paper data.

        This minimal parsing just extracts the paper data,
        leaving detailed mapping to a separate mapper component.

        Args:
            raw_data: JSON response from API

        Returns:
            List of raw paper records
        """
        if isinstance(raw_data, (str, bytes)):
            # Should not happen with ChemRxiv JSON API
            logger.warning("Unexpected string/bytes response from ChemRxiv API")
            return []

        papers = []

        # Handle response structure
        if isinstance(raw_data, dict):
            # Check if it's a list response with itemHits
            if "itemHits" in raw_data:
                for hit in raw_data.get("itemHits", []):
                    if "item" in hit:
                        paper_data = hit["item"]
                        paper_data["source"] = "chemrxiv"
                        papers.append(paper_data)
            # Handle single item response
            elif "id" in raw_data:
                raw_data["source"] = "chemrxiv"
                papers.append(raw_data)
            else:
                logger.warning(
                    f"Unexpected response structure: {list(raw_data.keys())}"
                )

        return papers

    def fetch_page(
        self,
        cursor: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        page_size: Optional[int] = None,
        **kwargs,
    ) -> PagedResponse:
        """
        Fetch a single page of ChemRxiv results using cursor-based pagination.

        Args:
            cursor: Cursor from previous request (None for first page)
            since: Start date for filtering (used on first request)
            until: End date for filtering (used on first request)
            page_size: Number of results per page
            **kwargs: Additional parameters

        Returns:
            PagedResponse with data and next cursor
        """
        # Parse cursor or initialize state
        if cursor:
            state = CursorState.from_cursor_string(cursor)
        else:
            # Initialize state for first request
            if until is None:
                until = datetime.now()
            if since is None:
                since = until - timedelta(days=7)

            state = CursorState(
                position=0,  # ChemRxiv uses skip parameter
                since=since,
                until=until,
                metadata={"source": "chemrxiv"},
            )

        # Use page_size from request or config
        if page_size is None:
            page_size = self.config.page_size

        # ChemRxiv API uses skip for pagination
        params = {
            "limit": page_size,
            "skip": state.position,
            "sort": "PUBLISHED_DATE_DESC",
        }

        logger.info(
            f"Fetching papers from ChemRxiv "
            f"(skip={state.position}, limit={page_size})"
        )

        try:
            response = self.fetch_with_retry("/items", params)
            papers = self.process_page(response)

            # Check for total count and pagination
            has_more = False
            total = None

            if isinstance(response, dict):
                total = response.get("totalCount")
                if total:
                    # Check if there are more results
                    has_more = (state.position + len(papers)) < total
                else:
                    # If no total count, assume more if we got full page
                    has_more = len(papers) == page_size
            else:
                # Fallback: assume more pages if we got full page
                has_more = len(papers) == page_size

            # Update state for next page
            next_state = None
            if has_more:
                next_state = CursorState(
                    position=state.position + len(papers),
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
            logger.error(f"Failed to fetch page at skip={state.position}: {e}")
            raise
