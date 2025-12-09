"""
ArXiv OAI client for fetching papers.

Implements the OAI standard for arXiv.

See: https://info.arxiv.org/help/oa/index.html
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ...exceptions import FetchError, TimeoutError
from ..base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


# XML namespaces for OAI parsing
_ARXIV_NS = "{http://arxiv.org/OAI/arXiv/}"
_ARXIV_RAW_NS = "{http://arxiv.org/OAI/arXivRaw/}"
_DC_NS = "{http://purl.org/dc/elements/1.1/}"


def _get_text(element: ET.Element, tag: str) -> Optional[str]:
    """
    Get text content from an XML element.

    Args:
        element: Parent element
        tag: Tag to find

    Returns:
        Text content or None
    """
    child = element.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return None


def _parse_dublin_core(root: ET.Element) -> Dict[str, Any]:
    """
    Parse Dublin Core metadata format as fallback.

    Args:
        root: Root XML element

    Returns:
        Dictionary with parsed fields
    """
    dc_elem = root.find(f".//{_DC_NS}dc")
    if dc_elem is None:
        return {}

    entry_data = {
        "title": _get_text(dc_elem, f"{_DC_NS}title"),
        "abstract": _get_text(dc_elem, f"{_DC_NS}description"),
        "created": _get_text(dc_elem, f"{_DC_NS}date"),
    }

    # Extract authors from creator fields
    authors = []
    for creator_elem in dc_elem.findall(f"{_DC_NS}creator"):
        if creator_elem.text:
            authors.append({"name": creator_elem.text.strip()})
    entry_data["authors"] = authors

    # Extract identifier (may contain arXiv ID)
    identifier = _get_text(dc_elem, f"{_DC_NS}identifier")
    if identifier and "arxiv.org" in identifier.lower():
        # Extract ID from URL
        if "/abs/" in identifier:
            entry_data["id"] = identifier.split("/abs/")[-1]
        elif ":" in identifier:
            entry_data["id"] = identifier.split(":")[-1]

    return entry_data


def parse_xml_metadata(raw_xml: str) -> Dict[str, Any]:
    """
    Parse raw OAI metadata XML into a dictionary.

    Args:
        raw_xml: Raw XML string for metadata section

    Returns:
        Dictionary with parsed fields
    """
    try:
        root = ET.fromstring(raw_xml)

        # The formats are possible: arXiv, arXivRaw, oai_dc (Dublin Core)
        # The following tries to parse for these formats in order.

        # Find `arXiv` metadata (standard format)
        arxiv_elem = root.find(f".//{_ARXIV_NS}arXiv")

        if arxiv_elem is None:
            # Try `arXivRaw` format
            arxiv_elem = root.find(f".//{_ARXIV_RAW_NS}arXivRaw")

        if arxiv_elem is None:
            # Try `oai_dc` format
            return _parse_dublin_core(root)

        # Determine which namespace to use
        ns = _ARXIV_NS if arxiv_elem.tag.startswith(_ARXIV_NS) else _ARXIV_RAW_NS

        # Extract basic fields
        entry_data: Dict[str, Any] = {
            "id": _get_text(arxiv_elem, f"{ns}id"),
            "title": _get_text(arxiv_elem, f"{ns}title"),
            "abstract": _get_text(arxiv_elem, f"{ns}abstract"),
            "created": _get_text(arxiv_elem, f"{ns}created"),
            "updated": _get_text(arxiv_elem, f"{ns}updated"),
        }

        # Extract authors
        authors: List[Dict[str, str]] = []
        authors_elem = arxiv_elem.find(f"{ns}authors")
        if authors_elem is not None:
            for author_elem in authors_elem.findall(f"{ns}author"):
                keyname = _get_text(author_elem, f"{ns}keyname")
                forenames = _get_text(author_elem, f"{ns}forenames")
                suffix = _get_text(author_elem, f"{ns}suffix")

                author_data = {}
                if forenames and keyname:
                    full_name = f"{forenames} {keyname}"
                    if suffix:
                        full_name += f" {suffix}"
                    author_data["name"] = full_name
                    author_data["keyname"] = keyname
                    author_data["forenames"] = forenames
                    if suffix:
                        author_data["suffix"] = suffix
                elif keyname:
                    author_data["name"] = keyname
                    author_data["keyname"] = keyname

                # Check for affiliation
                affiliation = _get_text(author_elem, f"{ns}affiliation")
                if affiliation:
                    author_data["affiliation"] = affiliation

                if author_data:
                    authors.append(author_data)

        entry_data["authors"] = authors

        # Extract categories
        categories_text = _get_text(arxiv_elem, f"{ns}categories")
        if categories_text:
            # Categories are space-separated
            entry_data["categories"] = categories_text.split()
            # First category is primary
            if entry_data["categories"]:
                entry_data["primary_category"] = entry_data["categories"][0]

        # Extract optional fields
        entry_data["comments"] = _get_text(arxiv_elem, f"{ns}comments")
        entry_data["journal_ref"] = _get_text(arxiv_elem, f"{ns}journal-ref")
        entry_data["doi"] = _get_text(arxiv_elem, f"{ns}doi")
        entry_data["license"] = _get_text(arxiv_elem, f"{ns}license")

        # Construct URLs from ArXiv ID
        if entry_data.get("id"):
            arxiv_id = entry_data["id"]
            entry_data["links"] = {
                "alternate": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
            }

        return entry_data

    except ET.ParseError as e:
        logger.error(f"Failed to parse OAI metadata XML: {e}")
        return {}


class ArXivOAIConfig(ClientConfig):
    """ArXiv OAI specific configuration."""

    def __init__(self, **kwargs):
        self.metadata_prefix = kwargs.pop(
            "metadata_prefix", "arXiv"
        )  # Possible values: oai_dc, arXiv, arXivRaw

        defaults = {
            "source_name": "arxiv_oai",
            "base_url": "https://oaipmh.arxiv.org/oai",
            "rate_limit": 0.33,  # 3 second delay between requests
            "request_timeout": 60.0,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class ArXivOAIClient(BaseClient):
    """
    Client for fetching papers from ArXiv using OAI protocol.

    See: https://info.arxiv.org/help/oa/index.html
    """

    # XML namespaces
    OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"

    def __init__(self, config: Optional[ArXivOAIConfig] = None):
        """
        Constructor.
        """
        if config is None:
            config = ArXivOAIConfig()
        super().__init__(config)
        self.session = requests.Session()

    def fetch(
        self, endpoint: str = "", params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> Union[str, bytes, Dict[str, Any]]:
        """
        Fetch data from ArXiv OAI API.

        Args:
            endpoint: API endpoint (not used for OAI).
            params: Query parameters.
            **kwargs: Additional arguments.

        Returns:
            XML response as string.

        Raises:
            FetchError: If request fails.
            TimeoutError: If request times out.
        """
        url = self.config.base_url

        try:
            response = self.session.get(
                url,
                params=params,
                timeout=self.config.request_timeout,
                headers={"Accept": "application/xml"},
            )
            response.raise_for_status()

            # Explicitly set encoding to UTF-8 to prevent double-encoding issues.
            # The response header does not specify any character encoding.
            # The response library assumes Latin-1 by default.
            response.encoding = "utf-8"

            # Check for OAI errors in response
            root = ET.fromstring(response.text)
            error_elem = root.find(f"{self.OAI_NS}error")
            if error_elem is not None:
                error_code = error_elem.get("code", "unknown")
                error_msg = error_elem.text or "Unknown error"
                raise FetchError(f"OAI error [{error_code}]: {error_msg}")

            return response.text

        except requests.Timeout:
            raise TimeoutError(
                f"Request timed out after {self.config.request_timeout}s"
            )
        except ET.ParseError as e:
            raise FetchError(f"Invalid XML response: {str(e)}")
        except requests.RequestException as e:
            raise FetchError(f"Failed to fetch from {url}: {str(e)}")

    def parse(
        self, raw_data: Union[str, bytes, Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Parse ArXiv OAI XML response and return parsed record data.

        Args:
            raw_data: XML response from API.

        Returns:
            List of parsed record dictionaries.
        """
        if isinstance(raw_data, dict):
            # If already parsed somehow, return as is
            return [raw_data] if raw_data else []

        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")

        papers = []
        try:
            root = ET.fromstring(raw_data)

            # Get `ListRecords` element
            list_records = root.find(f"{self.OAI_NS}ListRecords")
            if list_records is None:
                return []

            records = list_records.findall(f"{self.OAI_NS}record")

            for record in records:
                # Check for deleted record
                header = record.find(f"{self.OAI_NS}header")
                if header is not None and header.get("status") == "deleted":
                    continue

                # Extract metadata
                metadata = record.find(f"{self.OAI_NS}metadata")
                if metadata is not None:
                    metadata_xml = ET.tostring(metadata, encoding="unicode")
                    parsed = parse_xml_metadata(metadata_xml)
                    if parsed:
                        parsed["source"] = "arxiv_oai"
                        papers.append(parsed)

        except ET.ParseError as e:
            logger.error(f"Failed to parse OAI XML response: {e}")
            return []

        return papers

    def _extract_resumption_token(self, xml_response: str) -> Optional[str]:
        """
        Extract resumption token from OAI response for pagination.

        Args:
            xml_response: XML response string

        Returns:
            Resumption token if present, None otherwise
        """
        try:
            root = ET.fromstring(xml_response)
            list_records = root.find(f"{self.OAI_NS}ListRecords")
            if list_records is not None:
                token_elem = list_records.find(f"{self.OAI_NS}resumptionToken")
                if token_elem is not None and token_elem.text:
                    return token_elem.text.strip()
        except ET.ParseError as e:
            logger.error(f"Failed to parse XML for resumption token: {e}")

        return None

    def fetch_recent(
        self,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        max_results: Optional[int] = None,
        **kwargs,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent papers from ArXiv using OAI within date range.

        Args:
            since: Start date (defaults to 7 days ago).
            until: End date (defaults to today).
            max_results: Maximum number of results to return (None for all).
            **kwargs: Additional parameters.

        Returns:
            List of raw paper records.
        """
        # Default date range: last 7 days
        if until is None:
            until = datetime.now()
        if since is None:
            since = until - timedelta(days=7)

        # Format dates for OAI (YYYY-MM-DD format)
        since_str = since.strftime("%Y-%m-%d")
        until_str = until.strftime("%Y-%m-%d")

        # Build initial request parameters
        params = {
            "verb": "ListRecords",
            "metadataPrefix": self.config.metadata_prefix,
            "from": since_str,
            "until": until_str,
        }

        all_papers = []
        resumption_token = None

        logger.info(
            f"Fetching papers from ArXiv OAI "
            f"(from={since_str}, until={until_str}, "
            f"metadataPrefix={self.config.metadata_prefix})"
        )

        while True:
            # If we have a resumption token, use it (replaces other params)
            if resumption_token:
                request_params = {
                    "verb": "ListRecords",
                    "resumptionToken": resumption_token,
                }
            else:
                request_params = params

            try:
                response = self.fetch_with_retry("", request_params)
                papers = self.process_page(response)

                if not papers:
                    # No more papers in this batch
                    break

                all_papers.extend(papers)

                # Check if we've reached the max_results limit
                if max_results and len(all_papers) >= max_results:
                    all_papers = all_papers[:max_results]
                    break

                # Check for resumption token to continue pagination
                resumption_token = self._extract_resumption_token(response)
                if not resumption_token:
                    # No more pages
                    break

            except Exception as e:
                logger.error(
                    f"Failed to fetch batch with token {resumption_token}: {e}"
                )
                # Continue with what we have
                break

        logger.info(
            f"Fetched {len(all_papers)} papers from ArXiv OAI "
            f"between {since_str} and {until_str}"
        )
        return all_papers
