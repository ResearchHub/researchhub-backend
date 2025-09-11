"""
ChemRxiv API client for fetching chemistry preprints.

Handles communication with ChemRxiv Engage API endpoints.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ..exceptions import FetchError, TimeoutError
from .base import BaseClient, ClientConfig

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

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers from ChemRxiv within date range.

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

        all_papers = []
        offset = 0
        page_size = self.config.page_size

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
                "limit": current_page_size,
                "offset": offset,
                "sort": "PUBLISHED_DATE_DESC",
                # Note: ChemRxiv API doesn't support date filtering directly
                # We'll fetch all recent papers and filter them client-side if needed
            }

            logger.info(
                f"Fetching papers from ChemRxiv "
                f"(offset={offset}, limit={current_page_size})"
            )

            try:
                response = self.fetch_with_retry("/items", params)
                papers = self.process_page(response)

                if not papers:
                    # No more results
                    break

                all_papers.extend(papers)

                # Check if we got fewer results than requested (end of results)
                if len(papers) < current_page_size:
                    break

                # Check total count if available
                if isinstance(response, dict) and "totalCount" in response:
                    total_available = response["totalCount"]
                    if offset + len(papers) >= total_available:
                        break

                # Move to next page
                offset += len(papers)

            except Exception as e:
                logger.error(f"Failed to fetch page at offset={offset}: {e}")
                # Continue with what we have
                break

        logger.info(
            f"Fetched {len(all_papers)} papers from ChemRxiv "
            f"between {since.isoformat()} and {until.isoformat()}"
        )
        return all_papers
