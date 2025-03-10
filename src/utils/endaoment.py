from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests


def search_nonprofit_orgs(
    search_term: Optional[str] = None,
    ntee_major_codes: Optional[str] = None,
    ntee_minor_codes: Optional[str] = None,
    countries: Optional[str] = None,
    count: int = 15,
    offset: int = 0,
) -> Dict[str, Any]:
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
        Dict[str, Any]: Response from the Endaoment API.
    """
    base_url = "https://api.endaoment.org/v1/sdk/orgs/search"

    # Build query parameters
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

    # Make request to Endaoment API
    try:
        response = requests.get(
            f"{base_url}?{urlencode(params)}",
            headers={"accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        # Log error and return error response
        return {
            "error": str(e),
            "status": (
                getattr(e.response, "status_code", 500)
                if hasattr(e, "response")
                else 500
            ),
        }
