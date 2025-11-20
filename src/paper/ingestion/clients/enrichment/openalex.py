"""
OpenAlex API client for fetching academic papers.

Handles communication with OpenAlex API endpoints.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ...exceptions import FetchError, TimeoutError
from ..base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


class OpenAlexConfig(ClientConfig):
    """OpenAlex-specific configuration."""

    def __init__(self, **kwargs):
        # Extract OpenAlex-specific config
        self.max_results_per_query = kwargs.pop("max_results_per_query", 200)
        self.email = kwargs.pop("email", None)  # Polite pool access

        defaults = {
            "source_name": "openalex",
            "base_url": "https://api.openalex.org",
            "rate_limit": 10.0,  # OpenAlex allows 10 requests per second (100k per day)
            "page_size": 200,  # OpenAlex max per_page is 200
            "request_timeout": 30.0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class OpenAlexClient(BaseClient):
    """Client for fetching papers from OpenAlex API."""

    def __init__(self, config: Optional[OpenAlexConfig] = None):
        """Initialize OpenAlex client."""
        if config is None:
            config = OpenAlexConfig()
        super().__init__(config)
        self.session = requests.Session()
        self.api_key = config.api_key

        self.headers = {"Accept": "application/json"}
        if config.email:
            # See: https://docs.openalex.org/how-to-use-the-api/rate-limits-and-authentication#the-polite-pool
            self.headers["User-Agent"] = f"mailto:{config.email}"

    def fetch(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from OpenAlex API.

        Args:
            endpoint: API endpoint (e.g., "/works")
            params: Query parameters
            **kwargs: Additional arguments

        Returns:
            JSON response as dict

        Raises:
            FetchError: If request fails
            TimeoutError: If request times out
        """
        url = f"{self.config.base_url}{endpoint}"

        if params is None:
            params = {}
        # Add API key, if available
        if self.api_key:
            params["api_key"] = self.api_key

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.config.request_timeout,
                headers=self.headers,
            )
            response.raise_for_status()

            # OpenAlex returns JSON
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
        Parse OpenAlex JSON response and return raw entry data.

        This minimal parsing just extracts the results list,
        leaving detailed mapping to a separate mapper component.

        Args:
            raw_data: JSON response from API

        Returns:
            List of raw paper records
        """
        if not isinstance(raw_data, dict):
            logger.error("Expected dict response from OpenAlex API")
            return []

        results = raw_data.get("results", [])

        papers = []
        for result in results:
            papers.append({"raw_data": result, "source": "openalex"})

        return papers

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers from OpenAlex within date range.

        Args:
            since: Start date (defaults to 7 days ago)
            until: End date (defaults to today)
            max_results: Maximum number of results to return
            filters: Additional OpenAlex filters
            **kwargs: Additional parameters

        Returns:
            List of raw paper records
        """
        # Default date range: last 7 days
        if until is None:
            until = datetime.now()
        if since is None:
            since = until - timedelta(days=7)

        # Format dates for OpenAlex (YYYY-MM-DD format)
        since_str = since.strftime("%Y-%m-%d")
        until_str = until.strftime("%Y-%m-%d")

        filter_parts = []

        # Add date range filter using publication_date
        filter_parts.append(f"from_publication_date:{since_str}")
        filter_parts.append(f"to_publication_date:{until_str}")

        # Add any additional filters
        if filters:
            for key, value in filters.items():
                filter_parts.append(f"{key}:{value}")

        filter_str = ",".join(filter_parts)

        all_papers = []
        cursor = "*"  # cursor-based pagination
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
                "filter": filter_str,
                "per-page": current_page_size,
                "cursor": cursor,
                "sort": "publication_date:desc",
            }

            logger.info(
                f"Fetching papers from OpenAlex "
                f"(cursor={cursor}, per_page={current_page_size})"
            )

            try:
                response = self.fetch_with_retry("/works", params)
                papers = self.process_page(response)

                if not papers:
                    break  # no more results

                all_papers.extend(papers)

                # Check for next page cursor
                meta = response.get("meta", {})
                next_cursor = meta.get("next_cursor")

                if not next_cursor or len(papers) < current_page_size:
                    break  # no more pages

                cursor = next_cursor

            except Exception as e:
                logger.error(f"Failed to fetch page with cursor={cursor}: {e}")
                break  # continue with the next page

        logger.info(
            f"Fetched {len(all_papers)} papers from OpenAlex "
            f"between {since_str} and {until_str}"
        )
        return all_papers

    def fetch_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a specific paper by DOI.

        Args:
            doi: The DOI to fetch

        Returns:
            Raw paper record or None if not found
        """
        # Clean DOI - remove any URL prefix to get just the DOI
        doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")

        # OpenAlex uses https://doi.org/ format in URLs
        encoded_doi = f"https://doi.org/{doi}"

        try:
            response = self.fetch_with_retry(f"/works/{encoded_doi}")
            if response:
                return {"raw_data": response, "source": "openalex"}
        except FetchError as e:
            logger.warning(f"Paper with DOI {doi} not found: {e}")

        return None

    def fetch_by_ids(
        self, ids: List[str], id_type: str = "doi"
    ) -> List[Dict[str, Any]]:
        """
        Fetch papers by a list of IDs.

        Args:
            ids: List of IDs to fetch
            id_type: Type of ID (doi, openalex, pmid, etc.)

        Returns:
            List of raw paper records
        """
        if not ids:
            return []

        # Build filter based on ID type
        if id_type == "doi":
            # Clean and format DOIs for OpenAlex
            cleaned_ids = [
                id.replace("https://doi.org/", "").replace("http://doi.org/", "")
                for id in ids
            ]
            formatted_ids = [f"https://doi.org/{id}" for id in cleaned_ids]
            filter_str = f"doi:{'|'.join(formatted_ids)}"
        elif id_type == "openalex":
            filter_str = f"openalex:{'|'.join(ids)}"
        elif id_type == "pmid":
            filter_str = f"pmid:{'|'.join(ids)}"
        else:
            logger.error(f"Unsupported ID type: {id_type}")
            return []

        params = {
            "filter": filter_str,
            "per-page": min(len(ids), self.config.page_size),
        }

        try:
            response = self.fetch_with_retry("/works", params)
            return self.process_page(response)
        except Exception as e:
            logger.error(f"Failed to fetch papers by IDs: {e}")
            return []
