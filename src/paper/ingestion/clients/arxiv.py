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
from .base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


class ArXivConfig(ClientConfig):
    """ArXiv-specific configuration."""

    def __init__(self, **kwargs):
        # Extract ArXiv-specific config
        self.max_results_per_query = kwargs.pop("max_results_per_query", 2000)

        defaults = {
            "source_name": "arxiv",
            "base_url": "https://export.arxiv.org/api",
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

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers from ArXiv within date range.

        Args:
            since: Start date (defaults to 7 days ago)
            until: End date (defaults to today)
            max_results: Maximum number of results to return
            **kwargs: Additional parameters

        Returns:
            List of raw paper records
        """
        # Default date range: last 7 days
        if until is None:
            until = datetime.now()
        if since is None:
            since = until - timedelta(days=7)

        # Format dates for ArXiv query (YYYYMMDDHHMM format)
        since_str = since.strftime("%Y%m%d%H%M")
        until_str = until.strftime("%Y%m%d%H%M")

        # Build search query with date range using lastUpdatedDate
        search_query = f"lastUpdatedDate:[{since_str} TO {until_str}]"

        all_papers = []
        start = 0
        page_size = min(self.config.page_size, self.config.max_results_per_query)

        # Determine total results to fetch
        if max_results:
            total_to_fetch = max_results
        else:
            total_to_fetch = float("inf")

        while len(all_papers) < total_to_fetch:
            # Calculate how many to fetch in this request
            remaining = total_to_fetch - len(all_papers)
            current_page_size = min(page_size, remaining)

            params = {
                "search_query": search_query,
                "start": start,
                "max_results": current_page_size,
                "sortBy": "lastUpdatedDate",
                "sortOrder": "descending",
            }

            logger.info(
                f"Fetching papers from ArXiv "
                f"(start={start}, max_results={current_page_size})"
            )

            try:
                response = self.fetch_with_retry("/query", params)

                root = ET.fromstring(response)
                total_results_elem = root.find(f"{self.OPENSEARCH_NS}totalResults")
                total_results = (
                    int(total_results_elem.text)
                    if total_results_elem is not None
                    else 0
                )

                papers = self.process_page(response)

                if not papers:
                    # Check if this is a spurious empty response
                    if start < total_results:
                        logger.warning(
                            f"ArXiv returned empty feed despite "
                            f"start={start} < totalResults={total_results}. "
                            f"Skipping to next batch."
                        )
                        # Skip ahead to try next batch
                        start += current_page_size
                        continue

                    # Truly no more results
                    break

                all_papers.extend(papers)

                # Check if we got fewer results than requested (end of results)
                if len(papers) < current_page_size:
                    break

                # Move to next page
                start += len(papers)

            except Exception as e:
                logger.error(f"Failed to fetch page at start={start}: {e}")
                # Continue with what we have
                break

        logger.info(
            f"Fetched {len(all_papers)} papers from ArXiv "
            f"between {since_str} and {until_str}"
        )
        return all_papers
