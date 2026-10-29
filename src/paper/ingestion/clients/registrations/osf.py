"""
OSF API client for fetching registrations (e.g. Lifecycle Journal submissions).

Handles communication with the OSF v2 API: https://developer.osf.io/
"""

import logging
from typing import Any

import requests

from paper.ingestion.exceptions import FetchError, TimeoutError

logger = logging.getLogger(__name__)


class OSFRegistrationClient:
    """Client for fetching a single registration from the OSF API."""

    BASE_URL = "https://api.osf.io/v2"

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.session = requests.Session()

    def fetch_registration(self, guid: str) -> dict[str, Any] | None:
        """
        Fetch a registration with its contributors and labelled form answers.

        Args:
            guid: OSF GUID of the registration (e.g. "wzubg")

        Returns:
            Registration record, or None if no public registration has this GUID.
        """
        registration = self._get(f"/registrations/{guid}/", {"embed": "provider"})
        if registration is None:
            return None
        data = registration["data"]

        contributors = self._get(
            f"/registrations/{guid}/bibliographic_contributors/",
            {"embed": "users", "page[size]": 100},
        )

        schema = data["relationships"].get("registration_schema", {}).get("data")
        labels = self._fetch_response_labels(schema["id"]) if schema else {}

        provider = data.get("embeds", {}).get("provider", {}).get("data", {})
        return {
            "id": data["id"],
            "attributes": data["attributes"],
            "provider": provider.get("attributes", {}).get("name"),
            "url": data["links"].get("html"),
            "contributors": [
                contributor["embeds"]["users"]["data"]["attributes"]
                for contributor in (contributors or {}).get("data", [])
                if "data" in contributor.get("embeds", {}).get("users", {})
            ],
            "response_labels": labels,
        }

    def _fetch_response_labels(self, schema_id: str) -> dict[str, str]:
        """
        Map each registration response key (e.g. "340-18") to its question label
        (e.g. "Short Title:"), so answers can be read without hardcoding keys.
        """
        blocks = self._get(
            f"/schemas/registrations/{schema_id}/schema_blocks/",
            {"page[size]": 200},
        )
        labels_by_group = {}
        keys_by_group = {}
        for block in (blocks or {}).get("data", []):
            attributes = block["attributes"]
            group = attributes.get("schema_block_group_key")
            if attributes.get("block_type") == "question-label":
                labels_by_group[group] = attributes.get("display_text", "")
            elif attributes.get("registration_response_key"):
                keys_by_group[group] = attributes["registration_response_key"]

        return {
            key: labels_by_group[group]
            for group, key in keys_by_group.items()
            if group in labels_by_group
        }

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.Timeout:
            raise TimeoutError(f"Request to {url} timed out", timeout=self.timeout)
        except requests.RequestException as e:
            raise FetchError(f"Request to {url} failed: {e}", source="osf")

        # Private, withdrawn-and-removed, or missing registrations
        if response.status_code in (401, 403, 404, 410):
            return None
        if not response.ok:
            raise FetchError(
                f"Request to {url} failed with {response.status_code}",
                source="osf",
                status_code=response.status_code,
            )
        return response.json()
