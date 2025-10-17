import logging
from typing import Dict, Optional

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)


class IdType:
    """
    Supported identifier types for Altmetric API.
    """

    DOI = "doi"
    ARXIV = "arxiv"


class AltmetricClient:
    """
    Client for interacting with the Altmetric API.
    Uses the free public API endpoint that doesn't require authentication.
    """

    BASE_URL = "https://api.altmetric.com/v1"
    DEFAULT_TIMEOUT = 10

    def __init__(self, timeout: int = DEFAULT_TIMEOUT):
        self.timeout = timeout
        self.headers = {
            "User-Agent": "ResearchHub/1.0",
            "Accept": "application/json",
        }

    def _fetch_by_id(self, id: str, id_type: str = IdType.DOI) -> Optional[Dict]:
        """
        Fetch Altmetric data for a given identifier.

        Args:
            id: The identifier of the paper (e.g., DOI, arXiv ID)
            id_type: The type of identifier ("doi", "arxiv", etc.)

        Returns:
            Dict containing Altmetric data if found, None otherwise
        """
        if not id_type:
            logger.debug("No ID type provided to fetch Altmetric data")
            return None

        url = f"{self.BASE_URL}/{id_type}/{id}"

        try:
            with retryable_requests_session() as session:
                response = session.get(url, headers=self.headers, timeout=self.timeout)

                if response.status_code == 200:
                    logger.info(
                        f"Successfully fetched Altmetric data for {id_type}: {id}"
                    )
                    return response.json()
                elif response.status_code == 404:
                    # Paper not found in Altmetric - this is common and not an error
                    logger.debug(
                        f"{id_type.upper()} {id} not found in Altmetric database"
                    )
                    return None
                elif response.status_code == 429:
                    # Rate limited - will trigger retry via retryable_requests_session
                    logger.warning(
                        f"Rate limited when fetching Altmetric data for {id_type}: {id}"
                    )
                    response.raise_for_status()
                else:
                    logger.error(
                        f"Unexpected status code {response.status_code} "
                        f"when fetching Altmetric data for {id_type}: {id}"
                    )
                    return None

        except Exception as e:
            logger.error(
                f"Error fetching Altmetric data for {id_type} {id}: {str(e)}",
                exc_info=True,
            )
            return None

    def fetch_by_arxiv_id(
        self, arxiv_id: str, strip_version: bool = True
    ) -> Optional[Dict]:
        """
        Fetch Altmetric data for a given arXiv ID.

        Args:
            arxiv_id: The arXiv ID of the paper to fetch data for
            strip_version: Whether to strip version suffix (e.g., v1) from arXiv ID
        Returns:
            Dict containing Altmetric data if found, None otherwise
        """
        if not arxiv_id:
            logger.debug("No arXiv ID provided to fetch Altmetric data")
            return None

        # Altmetric does not recognize versioned arXiv IDs,
        # so strip version if present (default behavior):
        if strip_version:
            arxiv_id = arxiv_id.rsplit("v", 1)[0]

        return self._fetch_by_id(arxiv_id, id_type=IdType.ARXIV)

    def fetch_by_doi(self, doi: str) -> Optional[Dict]:
        """
        Fetch Altmetric data for a given DOI.

        Args:
            doi: The DOI of the paper to fetch data for
        Returns:
            Dict containing Altmetric data if found, None otherwise
        """
        if not doi:
            logger.debug("No DOI provided to fetch Altmetric data")
            return None

        cleaned_doi = self._clean_doi(doi)
        return self._fetch_by_id(cleaned_doi, id_type=IdType.DOI)

    @staticmethod
    def _clean_doi(doi: str) -> str:
        """
        Clean a DOI by removing URL prefixes and normalizing format.

        Args:
            doi: Raw DOI string

        Returns:
            Cleaned DOI string
        """
        # Remove common URL prefixes
        if doi.startswith("http"):
            # Handle both http://doi.org/ and https://dx.doi.org/ formats
            for prefix in ["doi.org/", "dx.doi.org/"]:
                if prefix in doi:
                    doi = doi.split(prefix)[-1]
                    break

        # Remove "doi:" prefix if present
        if doi.lower().startswith("doi:"):
            doi = doi[4:]

        return doi.strip()
