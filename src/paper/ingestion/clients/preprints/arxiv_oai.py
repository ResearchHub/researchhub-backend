"""
ArXiv OAI client for fetching papers.

Implements the OAI standard for arXiv.

See: https://info.arxiv.org/help/oa/index.html
"""

import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union

import requests

from ...exceptions import FetchError, TimeoutError
from ..base import BaseClient, ClientConfig

logger = logging.getLogger(__name__)


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
        Parse ArXiv OAI XML response and return raw record data.

        This minimal parsing extracts the XML text for each record,
        leaving detailed mapping to a separate mapper component.

        Args:
            raw_data: XML response from API.

        Returns:
            List of raw record dictionaries with XML data.
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
                    # Convert the entire metadata element to XML string
                    metadata_xml = ET.tostring(metadata, encoding="unicode")
                    papers.append({"raw_xml": metadata_xml, "source": "arxiv_oai"})

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
