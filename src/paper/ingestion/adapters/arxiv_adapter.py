"""
arXiv adapter for paper ingestion

Supports both the arXiv API and OAI-PMH protocol for bulk harvesting.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import quote

import structlog

from ..core.base_adapter import BaseAdapter

logger = structlog.get_logger(__name__)


class ArxivAdapter(BaseAdapter):
    """
    Adapter for arXiv papers

    Uses two APIs:
    1. arXiv API for search and individual papers
    2. OAI-PMH for bulk harvesting with resumption tokens
    """

    SOURCE_NAME = "arxiv"
    DEFAULT_RATE_LIMIT = "1/3s"  # Respectful rate limit per arXiv guidelines
    BASE_URL = "https://export.arxiv.org/api/query"
    OAI_BASE_URL = "https://export.arxiv.org/oai2"

    # Default categories to fetch (can be overridden)
    DEFAULT_CATEGORIES = [
        "cs.AI",
        "cs.LG",
        "cs.CL",  # AI/ML
        "q-bio",
        "physics.bio-ph",  # Biology
        "math",
        "stat",  # Math/Stats
    ]

    def __init__(
        self, rate_limit: Optional[str] = None, categories: Optional[List[str]] = None
    ):
        """
        Initialize arXiv adapter

        Args:
            rate_limit: Override rate limit
            categories: List of arXiv categories to fetch
        """
        super().__init__(rate_limit=rate_limit)
        self.categories = categories or self.DEFAULT_CATEGORIES

    def fetch_recent(self, hours: int = 24) -> Iterator[Dict[str, Any]]:
        """
        Fetch recent papers using the arXiv API

        Args:
            hours: Number of hours to look back

        Yields:
            Batches of raw response data
        """
        # Calculate date range
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(hours=hours)

        # Use submittedDate for recent papers
        date_query = f"submittedDate:[{start_date.strftime('%Y%m%d')}0000 TO {end_date.strftime('%Y%m%d')}2359]"

        # Build category query
        cat_query = " OR ".join([f"cat:{cat}" for cat in self.categories])

        # Combine queries
        search_query = f"({cat_query}) AND {date_query}"

        # Fetch with pagination
        start = 0
        max_results = 100

        while True:
            params = {
                "search_query": search_query,
                "start": start,
                "max_results": max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            response = self._make_request(self.BASE_URL, params=params)

            # Parse to check if we have more results
            root = ET.fromstring(response.text)
            entries = root.findall("{http://www.w3.org/2005/Atom}entry")

            if not entries:
                break

            yield {
                "source": "arxiv_api",
                "query": search_query,
                "start": start,
                "response": response.text,
                "count": len(entries),
            }

            # Check if there are more results
            total_results = int(
                root.find("{http://a9.com/-/spec/opensearch/1.1/}totalResults").text
            )
            start += max_results

            if start >= total_results:
                break

            logger.info(f"Fetched {start}/{total_results} arXiv papers")

    def fetch_date_range(
        self, start_date: datetime, end_date: datetime
    ) -> Iterator[Dict[str, Any]]:
        """
        Fetch papers using OAI-PMH for efficient bulk harvesting

        Args:
            start_date: Start of date range
            end_date: End of date range

        Yields:
            Batches of raw response data
        """
        # Format dates for OAI-PMH
        from_date = start_date.strftime("%Y-%m-%d")
        until_date = end_date.strftime("%Y-%m-%d")

        # OAI-PMH parameters
        params = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "from": from_date,
            "until": until_date,
        }

        resumption_token = None
        batch_count = 0

        while True:
            if resumption_token:
                # Use resumption token for subsequent requests
                params = {"verb": "ListRecords", "resumptionToken": resumption_token}

            response = self._make_request(self.OAI_BASE_URL, params=params)
            batch_count += 1

            # Parse response
            root = ET.fromstring(response.text)

            # Check for errors
            error = root.find(".//{http://www.openarchives.org/OAI/2.0/}error")
            if error is not None:
                error_code = error.get("code")
                error_msg = error.text
                logger.error(f"OAI-PMH error: {error_code} - {error_msg}")
                break

            # Count records in this batch
            records = root.findall(".//{http://www.openarchives.org/OAI/2.0/}record")

            yield {
                "source": "arxiv_oai",
                "from": from_date,
                "until": until_date,
                "batch": batch_count,
                "response": response.text,
                "count": len(records),
            }

            # Check for resumption token
            token_elem = root.find(
                ".//{http://www.openarchives.org/OAI/2.0/}resumptionToken"
            )
            if token_elem is not None and token_elem.text:
                resumption_token = token_elem.text
                complete_list_size = token_elem.get("completeListSize")
                cursor = token_elem.get("cursor")
                logger.info(
                    f"OAI-PMH progress: {cursor}/{complete_list_size}",
                    resumption_token=resumption_token[:20] + "...",
                )
            else:
                # No more results
                break

    def parse_response(self, response_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse arXiv API or OAI-PMH response into standard format

        Args:
            response_data: Raw response with 'source' and 'response' fields

        Returns:
            List of parsed papers
        """
        source_type = response_data.get("source", "")
        raw_xml = response_data.get("response", "")

        if source_type == "arxiv_api":
            return self._parse_api_response(raw_xml)
        elif source_type == "arxiv_oai":
            return self._parse_oai_response(raw_xml)
        else:
            logger.error(f"Unknown source type: {source_type}")
            return []

    def _parse_api_response(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse arXiv API response"""
        papers = []
        root = ET.fromstring(xml_data)

        # Define namespaces
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        for entry in root.findall("atom:entry", ns):
            try:
                # Extract ID
                arxiv_id = entry.find("atom:id", ns).text.split("/")[-1]

                # Extract version from ID if present
                if "v" in arxiv_id:
                    base_id, version = arxiv_id.rsplit("v", 1)
                else:
                    base_id = arxiv_id
                    version = "1"

                # Extract title
                title = entry.find("atom:title", ns).text.strip()

                # Extract abstract
                summary = entry.find("atom:summary", ns).text.strip()

                # Extract authors
                authors = []
                for author in entry.findall("atom:author", ns):
                    name = author.find("atom:name", ns).text
                    # Try to split into first/last
                    name_parts = name.rsplit(" ", 1)
                    if len(name_parts) == 2:
                        given, family = name_parts
                    else:
                        given = ""
                        family = name

                    author_dict = {"given": given, "family": family, "name": name}

                    # Add affiliation if available
                    affiliation = author.find("arxiv:affiliation", ns)
                    if affiliation is not None:
                        author_dict["affiliation"] = affiliation.text

                    authors.append(author_dict)

                # Extract dates
                published = entry.find("atom:published", ns).text
                updated = entry.find("atom:updated", ns).text

                # Extract categories
                categories = []
                primary_category = entry.find("arxiv:primary_category", ns)
                if primary_category is not None:
                    categories.append(primary_category.get("term"))

                for category in entry.findall("atom:category", ns):
                    term = category.get("term")
                    if term and term not in categories:
                        categories.append(term)

                # Extract DOI if available
                doi = None
                doi_elem = entry.find("arxiv:doi", ns)
                if doi_elem is not None:
                    doi = doi_elem.text

                # Extract comment (often contains journal info)
                comment = None
                comment_elem = entry.find("arxiv:comment", ns)
                if comment_elem is not None:
                    comment = comment_elem.text

                # Extract links
                pdf_url = f"https://arxiv.org/pdf/{base_id}.pdf"
                abs_url = f"https://arxiv.org/abs/{base_id}"

                paper = {
                    "title": title,
                    "abstract": summary,
                    "authors": authors,
                    "published_date": published,
                    "updated_date": updated,
                    "doi": doi,
                    "arxiv_id": base_id,
                    "version": version,
                    "source_id": arxiv_id,
                    "pdf_url": pdf_url,
                    "url": abs_url,
                    "categories": categories,
                    "primary_category": categories[0] if categories else None,
                    "comment": comment,
                    "metadata": {
                        "source": "arxiv",
                        "arxiv_id": arxiv_id,
                        "categories": categories,
                        "comment": comment,
                    },
                }

                papers.append(paper)

            except Exception as e:
                logger.error(f"Error parsing arXiv entry: {e}")
                continue

        return papers

    def _parse_oai_response(self, xml_data: str) -> List[Dict[str, Any]]:
        """Parse OAI-PMH response"""
        papers = []
        root = ET.fromstring(xml_data)

        # Define namespaces
        ns = {
            "oai": "http://www.openarchives.org/OAI/2.0/",
            "arxiv": "http://arxiv.org/OAI/arXiv/",
        }

        for record in root.findall(".//oai:record", ns):
            try:
                # Check if record is deleted
                header = record.find("oai:header", ns)
                if header.get("status") == "deleted":
                    continue

                # Get metadata
                metadata = record.find(".//arxiv:arXiv", ns)
                if metadata is None:
                    continue

                # Extract ID
                arxiv_id = metadata.find("arxiv:id", ns).text

                # Extract title
                title = metadata.find("arxiv:title", ns).text.strip()

                # Extract abstract
                abstract = metadata.find("arxiv:abstract", ns).text.strip()

                # Extract authors
                authors = []
                authors_elem = metadata.find("arxiv:authors", ns)
                if authors_elem is not None:
                    for author in authors_elem.findall("arxiv:author", ns):
                        keyname = author.find("arxiv:keyname", ns)
                        forenames = author.find("arxiv:forenames", ns)

                        author_dict = {}
                        if keyname is not None:
                            author_dict["family"] = keyname.text
                        if forenames is not None:
                            author_dict["given"] = forenames.text

                        # Combine for full name
                        if forenames is not None and keyname is not None:
                            author_dict["name"] = f"{forenames.text} {keyname.text}"

                        authors.append(author_dict)

                # Extract dates
                created = metadata.find("arxiv:created", ns).text
                updated = metadata.find("arxiv:updated", ns)
                updated_date = updated.text if updated is not None else created

                # Extract categories
                categories = []
                categories_elem = metadata.find("arxiv:categories", ns)
                if categories_elem is not None:
                    categories = categories_elem.text.split()

                # Extract DOI
                doi = None
                doi_elem = metadata.find("arxiv:doi", ns)
                if doi_elem is not None:
                    doi = doi_elem.text

                # Extract license
                license_elem = metadata.find("arxiv:license", ns)
                license_url = license_elem.text if license_elem is not None else None

                # Build URLs
                pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                abs_url = f"https://arxiv.org/abs/{arxiv_id}"

                paper = {
                    "title": title,
                    "abstract": abstract,
                    "authors": authors,
                    "published_date": created,
                    "updated_date": updated_date,
                    "doi": doi,
                    "arxiv_id": arxiv_id,
                    "source_id": arxiv_id,
                    "pdf_url": pdf_url,
                    "url": abs_url,
                    "categories": categories,
                    "primary_category": categories[0] if categories else None,
                    "license": license_url,
                    "metadata": {
                        "source": "arxiv_oai",
                        "arxiv_id": arxiv_id,
                        "categories": categories,
                        "license": license_url,
                    },
                }

                papers.append(paper)

            except Exception as e:
                logger.error(f"Error parsing OAI record: {e}")
                continue

        logger.info(f"Parsed {len(papers)} papers from arXiv OAI-PMH response")
        return papers

    def fetch_by_id(self, arxiv_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single paper by arXiv ID

        Args:
            arxiv_id: arXiv identifier (e.g., "2301.00001" or "math.GT/0309136")

        Returns:
            Raw response data
        """
        # Clean the ID
        arxiv_id = arxiv_id.replace("arXiv:", "")

        params = {"id_list": arxiv_id}

        response = self._make_request(self.BASE_URL, params=params)

        return {
            "source": "arxiv_api",
            "query": f"id:{arxiv_id}",
            "response": response.text,
            "count": 1,
        }
