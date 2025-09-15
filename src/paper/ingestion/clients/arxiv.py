"""
ArXiv API client for fetching papers.

Handles communication with ArXiv API endpoints.
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig, CursorState, PagedResponse

logger = logging.getLogger(__name__)


class ArXivConfig(ClientConfig):
    """ArXiv-specific configuration."""

    def __init__(self, **kwargs):
        # Extract ArXiv-specific config
        self.max_results_per_query = kwargs.pop("max_results_per_query", 2000)

        defaults = {
            "source_name": "arxiv",
            "base_url": "http://export.arxiv.org/api",  # NOSONAR - ArXiv API uses HTTP
            "rate_limit": 0.33,  # Recommended 3 second delay between requests
            "page_size": 100,  # ArXiv recommends smaller batches for better performance
            "request_timeout": 30.0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class ArXivClient(BaseClient):
    """Client for fetching papers from ArXiv API."""

    # ArXiv XML namespaces
    ATOM_NS = "{http://www.w3.org/2005/Atom}"
    ARXIV_NS = "{http://arxiv.org/schemas/atom}"
    OPENSEARCH_NS = "{http://a9.com/-/spec/opensearch/1.1/}"

    def __init__(self, config: Optional[ArXivConfig] = None):
        """Initialize ArXiv client."""
        if config is None:
            config = ArXivConfig()
        super().__init__(config)
        self.session = requests.Session()

    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from ArXiv API.

        Args:
            endpoint: API endpoint (typically "/query")
            params: Query parameters
            **kwargs: Additional arguments

        Returns:
            XML response as string

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
                headers={"Accept": "application/atom+xml"},
            )
            response.raise_for_status()

            # ArXiv returns XML
            return response.text

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
        Parse ArXiv Atom XML feed and return raw entry data.

        This minimal parsing just extracts the XML text for each entry,
        leaving detailed mapping to a separate mapper component.

        Args:
            raw_data: XML response from API

        Returns:
            List of raw entry XML strings
        """
        if isinstance(raw_data, dict):
            # If already parsed somehow, return as is
            return [raw_data] if raw_data else []

        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")

        papers = []
        try:
            root = ET.fromstring(raw_data)

            # Find all entry elements and return their raw XML
            entries = root.findall(f"{self.ATOM_NS}entry")

            for entry in entries:
                # Convert each entry back to XML string
                entry_xml = ET.tostring(entry, encoding="unicode")
                papers.append({"raw_xml": entry_xml, "source": "arxiv"})

        except ET.ParseError as e:
            logger.error(f"Failed to parse XML response: {e}")
            return []

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
        Fetch a single page of ArXiv results using cursor-based pagination.

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
                position=0,
                since=since,
                until=until,
                metadata={"source": "arxiv"},
            )

        # Use page_size from request or config
        if page_size is None:
            page_size = min(self.config.page_size, self.config.max_results_per_query)

        # Format dates for ArXiv query (YYYYMMDD format)
        since_str = state.since.strftime("%Y%m%d")
        until_str = state.until.strftime("%Y%m%d")

        # Build search query with date range using submittedDate
        search_query = f"submittedDate:[{since_str} TO {until_str}]"

        params = {
            "search_query": search_query,
            "start": state.position,
            "max_results": page_size,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        logger.info(
            f"Fetching papers from ArXiv "
            f"(start={state.position}, max_results={page_size})"
        )

        try:
            response = self.fetch_with_retry("/query", params)
            papers = self.process_page(response)

            # Check if there are more results
            has_more = len(papers) == page_size

            # Update state for next page
            next_state = None
            if has_more:
                next_state = CursorState(
                    position=state.position + len(papers),
                    since=state.since,
                    until=state.until,
                    has_more=True,
                    metadata=state.metadata,
                )

            return PagedResponse(
                data=papers,
                cursor=next_state.to_cursor_string() if next_state else None,
                has_more=has_more,
                total=state.total,  # ArXiv doesn't provide total count easily
            )

        except Exception as e:
            logger.error(f"Failed to fetch page at start={state.position}: {e}")
            raise
