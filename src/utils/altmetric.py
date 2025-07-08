import logging
import time
from typing import Dict, Optional

from utils.retryable_requests import retryable_requests_session

logger = logging.getLogger(__name__)


class Altmetric:
    """
    Client for interacting with the Altmetric API.
    Uses the free public API endpoint that doesn't require authentication.
    """

    def __init__(self, timeout: int = 10):
        self.base_url = "https://api.altmetric.com/v1"
        self.timeout = timeout
        self.base_headers = {
            "User-Agent": "ResearchHub/1.0 (hello@researchhub.com)",
            "Accept": "application/json",
        }

    def get_altmetric_data(self, doi: str) -> Optional[Dict]:
        """
        Fetch Altmetric data for a given DOI.

        Args:
            doi: The DOI of the paper to fetch data for

        Returns:
            Dict containing Altmetric data if found, None otherwise
        """
        if not doi:
            return None

        # Clean the DOI - remove any URL prefix if present
        if doi.startswith("http"):
            doi = doi.split("doi.org/")[-1]

        url = f"{self.base_url}/doi/{doi}"

        try:
            with retryable_requests_session() as session:
                response = session.get(
                    url, headers=self.base_headers, timeout=self.timeout
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 404:
                    # Paper not found in Altmetric - this is common and not an error
                    logger.debug(f"DOI {doi} not found in Altmetric")
                    return None
                elif response.status_code == 429:
                    # Rate limited - this will trigger a retry
                    logger.warning(
                        f"Rate limited when fetching Altmetric data for DOI {doi}"
                    )
                    response.raise_for_status()
                else:
                    logger.error(
                        f"Unexpected status code {response.status_code} "
                        f"when fetching Altmetric data for DOI {doi}"
                    )
                    return None
        except Exception as e:
            logger.error(
                f"Error fetching Altmetric data for DOI {doi}: {str(e)}", exc_info=True
            )
            return None

    def batch_get_altmetric_data(
        self, dois: list, delay: float = 0.5
    ) -> Dict[str, Optional[Dict]]:
        """
        Fetch Altmetric data for multiple DOIs with a delay between requests.

        Args:
            dois: List of DOIs to fetch data for
            delay: Delay in seconds between requests (default 0.5s)

        Returns:
            Dict mapping DOI to Altmetric data (or None if not found)
        """
        results = {}

        for i, doi in enumerate(dois):
            if i > 0:
                # Add delay between requests to be respectful of the API
                time.sleep(delay)

            results[doi] = self.get_altmetric_data(doi)

            # Log progress every 10 papers
            if (i + 1) % 10 == 0:
                logger.info(f"Processed {i + 1}/{len(dois)} papers for Altmetric data")

        return results
