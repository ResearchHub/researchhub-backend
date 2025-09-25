import logging
from typing import Dict, Optional

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)


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

        # Clean the DOI - remove any URL prefix if present
        cleaned_doi = self._clean_doi(doi)
        url = f"{self.BASE_URL}/doi/{cleaned_doi}"

        try:
            with retryable_requests_session() as session:
                response = session.get(url, headers=self.headers, timeout=self.timeout)

                if response.status_code == 200:
                    logger.info(
                        f"Successfully fetched Altmetric data for DOI: {cleaned_doi}"
                    )
                    return response.json()
                elif response.status_code == 404:
                    # Paper not found in Altmetric - this is common and not an error
                    logger.debug(f"DOI {cleaned_doi} not found in Altmetric database")
                    return None
                elif response.status_code == 429:
                    # Rate limited - will trigger retry via retryable_requests_session
                    logger.warning(
                        f"Rate limited when fetching Altmetric data for DOI: {cleaned_doi}"
                    )
                    response.raise_for_status()
                else:
                    logger.error(
                        f"Unexpected status code {response.status_code} "
                        f"when fetching Altmetric data for DOI: {cleaned_doi}"
                    )
                    return None

        except Exception as e:
            logger.error(
                f"Error fetching Altmetric data for DOI {cleaned_doi}: {str(e)}",
                exc_info=True,
            )
            return None

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
