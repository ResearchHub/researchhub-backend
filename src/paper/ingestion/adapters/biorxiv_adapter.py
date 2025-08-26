"""
bioRxiv and medRxiv adapter for paper ingestion

Both preprint servers use the same API structure.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional

import structlog

from ..core.base_adapter import BaseAdapter

logger = structlog.get_logger(__name__)


class BiorxivMedrxivAdapter(BaseAdapter):
    """
    Adapter for bioRxiv and medRxiv papers

    API Documentation: https://api.biorxiv.org/
    Both servers use identical API endpoints with different server names.
    """

    SOURCE_NAME = "biorxiv"  # Override for medrxiv
    DEFAULT_RATE_LIMIT = "100/m"  # No documented limit, being conservative

    # API endpoints
    DETAILS_ENDPOINT = (
        "https://api.biorxiv.org/details/{server}/{interval}/{cursor}/{format}"
    )
    PUBS_ENDPOINT = "https://api.biorxiv.org/pubs/{server}/{interval}/{cursor}/{format}"

    def __init__(self, server: str = "biorxiv", rate_limit: Optional[str] = None):
        """
        Initialize bioRxiv/medRxiv adapter

        Args:
            server: Either "biorxiv" or "medrxiv"
            rate_limit: Override rate limit
        """
        if server not in ["biorxiv", "medrxiv"]:
            raise ValueError(
                f"Invalid server: {server}. Must be 'biorxiv' or 'medrxiv'"
            )

        self.server = server
        self.SOURCE_NAME = server
        super().__init__(rate_limit=rate_limit)

    def fetch_recent(self, hours: int = 24) -> Iterator[Dict[str, Any]]:
        """
        Fetch recent papers from the last N hours

        Args:
            hours: Number of hours to look back (max 7 days supported by API)

        Yields:
            Batches of raw response data
        """
        # API supports fetching by number of days with 'd' suffix
        if hours <= 24:
            interval = "1d"
        elif hours <= 48:
            interval = "2d"
        elif hours <= 72:
            interval = "3d"
        elif hours <= 168:  # 7 days
            interval = "7d"
        else:
            # For longer periods, use date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(hours=hours)
            yield from self.fetch_date_range(start_date, end_date)
            return

        # Fetch using interval API
        cursor = 0
        total_fetched = 0

        while True:
            url = self.DETAILS_ENDPOINT.format(
                server=self.server, interval=interval, cursor=cursor, format="json"
            )

            response = self._make_request(url)
            data = response.json()

            # Check for messages (API metadata)
            messages = data.get("messages", [])
            if messages:
                for msg in messages:
                    if "count" in msg:
                        total_count = msg["count"]
                        logger.info(f"Total papers available: {total_count}")

            # Get papers from collection
            papers = data.get("collection", [])
            if not papers:
                break

            total_fetched += len(papers)

            yield {
                "source": f"{self.server}_api",
                "interval": interval,
                "cursor": cursor,
                "response": json.dumps(data),
                "count": len(papers),
            }

            # API returns 100 results per call
            # If we got less than 100, we've reached the end
            if len(papers) < 100:
                break

            cursor += 100
            logger.info(f"Fetched {total_fetched} papers from {self.server}")

    def fetch_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch papers within a date range

        Args:
            start_date: Start of date range
            end_date: End of date range

        Yields:
            Batches of raw response data
        """
        # Format dates as YYYY-MM-DD
        from_date = start_date.strftime("%Y-%m-%d")
        to_date = end_date.strftime("%Y-%m-%d")

        # Build interval string
        interval = f"{from_date}/{to_date}"

        cursor = 0
        total_fetched = 0

        while True:
            url = self.DETAILS_ENDPOINT.format(
                server=self.server, interval=interval, cursor=cursor, format="json"
            )

            response = self._make_request(url)
            data = response.json()

            # Check for messages
            messages = data.get("messages", [])
            if messages:
                for msg in messages:
                    if "count" in msg:
                        total_count = msg["count"]
                        logger.info(
                            f"Total papers for {from_date} to {to_date}: {total_count}",
                            server=self.server,
                        )

            # Get papers
            papers = data.get("collection", [])
            if not papers:
                break

            total_fetched += len(papers)

            yield {
                "source": f"{self.server}_api",
                "from_date": from_date,
                "to_date": to_date,
                "cursor": cursor,
                "response": json.dumps(data),
                "count": len(papers),
            }

            # Check if we've fetched all papers
            if len(papers) < 100:
                break

            cursor += 100
            logger.info(f"Fetched {total_fetched} papers from {self.server}")

    def parse_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse bioRxiv/medRxiv API response into standard format

        Args:
            response_data: Raw response with 'response' field containing JSON

        Returns:
            List of parsed papers
        """
        papers = []

        try:
            # Parse JSON response
            data = json.loads(response_data.get("response", "{}"))
            collection = data.get("collection", [])

            for item in collection:
                try:
                    # Extract basic fields
                    title = item.get("title", "").strip()
                    abstract = item.get("abstract", "").strip()

                    # Parse authors
                    authors = []
                    authors_str = item.get("authors", "")
                    if authors_str:
                        # Authors are in format: "LastName, FirstName; LastName, FirstName"
                        author_parts = authors_str.split(";")
                        for author_part in author_parts:
                            author_part = author_part.strip()
                            if ", " in author_part:
                                family, given = author_part.split(", ", 1)
                                authors.append(
                                    {
                                        "given": given.strip(),
                                        "family": family.strip(),
                                        "name": author_part,
                                    }
                                )
                            else:
                                authors.append(
                                    {
                                        "name": author_part,
                                        "family": author_part,
                                        "given": "",
                                    }
                                )

                    # Extract dates
                    date_str = item.get("date", "")
                    published_date = item.get("published", date_str)

                    # Extract DOI
                    doi = item.get("doi", "")
                    if doi and not doi.startswith("10."):
                        # Sometimes DOI is returned as full URL
                        if "doi.org/" in doi:
                            doi = doi.split("doi.org/")[-1]

                    # Extract version
                    version = str(item.get("version", 1))

                    # Category/subject
                    category = item.get("category", "")

                    # Server (biorxiv or medrxiv)
                    server = item.get("server", self.server)

                    # Build URLs
                    if doi:
                        pdf_url = (
                            f"https://www.{server}.org/content/{doi}v{version}.full.pdf"
                        )
                        abs_url = f"https://www.{server}.org/content/{doi}v{version}"
                    else:
                        # Fallback if no DOI
                        pdf_url = None
                        abs_url = None

                    # Get additional metadata
                    jats_xml_path = item.get("jatsxml", "")
                    license = item.get("license", "")
                    published_journal = item.get("published_citation_doi", "")

                    paper = {
                        "title": title,
                        "abstract": abstract,
                        "authors": authors,
                        "published_date": published_date,
                        "doi": doi,
                        "source_id": f"{server}:{doi}v{version}" if doi else None,
                        "pdf_url": pdf_url,
                        "url": abs_url,
                        "version": version,
                        "category": category,
                        "server": server,
                        "metadata": {
                            "source": server,
                            "doi": doi,
                            "version": version,
                            "category": category,
                            "license": license,
                            "jats_xml": jats_xml_path,
                            "published_doi": published_journal,
                            "author_corresponding": item.get(
                                "author_corresponding", ""
                            ),
                            "author_corresponding_institution": item.get(
                                "author_corresponding_institution", ""
                            ),
                        },
                    }

                    # Add bioRxiv/medRxiv specific DOI field
                    if server == "biorxiv":
                        paper["biorxiv_doi"] = doi
                    else:
                        paper["medrxiv_doi"] = doi

                    papers.append(paper)

                except Exception as e:
                    logger.error(f"Error parsing {self.server} paper: {e}", item=item)
                    continue

        except Exception as e:
            logger.error(f"Error parsing {self.server} response: {e}")

        logger.info(f"Parsed {len(papers)} papers from {self.server} response")
        return papers

    def fetch_by_doi(self, doi: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single paper by DOI

        Args:
            doi: DOI identifier (without prefix like "10.1101/")

        Returns:
            Raw response data
        """
        # Clean DOI
        if doi.startswith("10.1101/"):
            doi = doi[8:]

        url = f"https://api.biorxiv.org/details/{self.server}/{doi}/na/json"

        try:
            response = self._make_request(url)
            data = response.json()

            return {
                "source": f"{self.server}_api",
                "doi": doi,
                "response": json.dumps(data),
                "count": len(data.get("collection", [])),
            }
        except Exception as e:
            logger.error(
                f"Error fetching {self.server} paper by DOI: {doi}", error=str(e)
            )
            return None

    def fetch_published_versions(
        self, start_date: datetime, end_date: datetime
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch papers that have been published in journals

        Uses the /pubs endpoint to get papers with publication info

        Args:
            start_date: Start of date range
            end_date: End of date range

        Yields:
            Batches of raw response data
        """
        from_date = start_date.strftime("%Y-%m-%d")
        to_date = end_date.strftime("%Y-%m-%d")
        interval = f"{from_date}/{to_date}"

        cursor = 0

        while True:
            url = self.PUBS_ENDPOINT.format(
                server=self.server, interval=interval, cursor=cursor, format="json"
            )

            response = self._make_request(url)
            data = response.json()

            papers = data.get("collection", [])
            if not papers:
                break

            yield {
                "source": f"{self.server}_pubs",
                "from_date": from_date,
                "to_date": to_date,
                "cursor": cursor,
                "response": json.dumps(data),
                "count": len(papers),
            }

            if len(papers) < 100:
                break

            cursor += 100
