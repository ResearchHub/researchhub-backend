import logging
import re
from typing import Any, Union
from urllib.parse import urlencode

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

UNKNOWN_NONPROFIT_NAME = "Unknown"


class EndaomentServiceError(Exception):
    """Raised when the Endaoment API cannot be reached or returns an error."""


class EndaomentOrgNotFound(Exception):
    """Raised when no Endaoment org matches the provided EIN and org id."""


def normalize_ein(ein: str) -> str:
    """Strip non-digit characters from an EIN."""
    return re.sub(r"\D", "", ein or "")


def default_org_search_url() -> str:
    return f"{settings.ENDAOMENT_API_URL}/v2/orgs/search"


def base_chain_id() -> int:
    """Base mainnet in production, Base Sepolia in non-production."""
    if settings.PRODUCTION:
        return settings.BASE_MAINNET_CHAIN_ID
    return settings.BASE_SEPOLIA_CHAIN_ID


def base_wallet_from_org(org: dict[str, Any]) -> str:
    """
    Extract the org's Base deployment contract address from an Endaoment org payload.
    """
    chain_id = base_chain_id()
    for deployment in org.get("deployments") or []:
        if deployment.get("chainId") == chain_id:
            return (deployment.get("contractAddress") or "").strip()
    return ""


def nonprofit_fields_from_org(org: dict[str, Any]) -> dict[str, str]:
    """Extract canonical nonprofit fields from a verified Endaoment org payload."""
    name = (org.get("name") or "").strip() or UNKNOWN_NONPROFIT_NAME
    return {
        "name": name,
        "ein": (org.get("ein") or "").strip(),
        "endaoment_org_id": (org.get("id") or "").strip(),
        "base_wallet_address": base_wallet_from_org(org),
    }


class EndaomentService:
    """Service for interacting with the Endaoment API."""

    def __init__(self, base_url: str | None = None):
        """Initialize the service with configurable base URL for testing."""
        self.base_url = base_url or default_org_search_url()

    def search_nonprofit_orgs(
        self,
        search_term: str | None = None,
        ntee_major_codes: str | None = None,
        ntee_minor_codes: str | None = None,
        countries: str | None = None,
        count: int = 15,
        offset: int = 0,
    ) -> Union[list[Any], dict[str, Any]]:
        """
        Search for nonprofit organizations using the Endaoment API.

        Args:
            search_term (str, optional): Term to search for nonprofit organizations.
            ntee_major_codes (str, optional): Comma-separated list of NTEE major codes.
            ntee_minor_codes (str, optional): Comma-separated list of NTEE minor codes.
            countries (str, optional): Comma-separated list of countries.
            count (int, optional): Number of results to return (default: 15).
            offset (int, optional): Offset for pagination (default: 0).

        Returns:
            List of org dicts on success, or error dict on failure.
        """
        params = {}

        if search_term:
            params["searchTerm"] = search_term
        if ntee_major_codes:
            params["nteeMajorCodes"] = ntee_major_codes
        if ntee_minor_codes:
            params["nteeMinorCodes"] = ntee_minor_codes
        if countries:
            params["countries"] = countries

        params["count"] = count
        params["offset"] = offset

        try:
            response = requests.get(
                f"{self.base_url}?{urlencode(params)}",
                headers={"accept": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(
                "Error searching nonprofit organizations: %s",
                str(e),
                extra={
                    "params": params,
                    "status_code": (
                        getattr(e.response, "status_code", 500)
                        if hasattr(e, "response")
                        else 500
                    ),
                },
                exc_info=True,
            )
            return {
                "error": str(e),
                "status": (
                    getattr(e.response, "status_code", 500)
                    if hasattr(e, "response")
                    else 500
                ),
            }

    def _find_matching_org(
        self,
        results: list[dict[str, Any]],
        normalized_ein: str,
        endaoment_org_id: str,
    ) -> dict[str, Any] | None:
        for org in results:
            if (
                normalize_ein(org.get("ein", "")) == normalized_ein
                and org.get("id") == endaoment_org_id
            ):
                return org
        return None

    def verify_nonprofit_org(self, ein: str, endaoment_org_id: str) -> dict[str, Any]:
        """
        Verify that a nonprofit exists on Endaoment with the given EIN and org id.

        Raises:
            EndaomentServiceError: If the Endaoment API is unreachable or errors.
            EndaomentOrgNotFound: If no matching org is found.
        """
        normalized_ein = normalize_ein(ein)
        result = self.search_nonprofit_orgs(search_term=normalized_ein)

        if isinstance(result, dict) and "error" in result:
            raise EndaomentServiceError(result["error"])

        if not isinstance(result, list):
            raise EndaomentServiceError("Unexpected response from Endaoment")

        match = self._find_matching_org(result, normalized_ein, endaoment_org_id)
        if match is not None:
            return match

        raise EndaomentOrgNotFound()
