"""
OpenAlex API Service Module

This module provides a service class for interacting with the OpenAlex API.
It encapsulates all API interactions in a single place, making it easier to:
1. Cache responses
2. Handle rate limiting
3. Implement backoff strategies
4. Manage error handling consistently
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from utils.openalex import OpenAlex


class OpenAlexService:
    """
    Service class for interacting with the OpenAlex API.

    This class provides methods for fetching works and authors from OpenAlex,
    with additional features like caching, error handling, and request batching.
    """

    def __init__(self, openalex_client=None):
        """
        Initialize the OpenAlex service.

        Args:
            openalex_client: Optional custom OpenAlex client instance
        """
        self.client = openalex_client or OpenAlex()
        self._cache = {}  # Simple in-memory cache

    def get_work(self, work_id: str) -> Dict[str, Any]:
        """
        Get a single work by ID.

        Args:
            work_id: The OpenAlex work ID (can be with or without the 'https://openalex.org/' prefix)

        Returns:
            Dict containing the work data
        """
        # Strip prefix if present
        if "/" in work_id:
            work_id = work_id.split("/")[-1]

        # Check cache
        cache_key = f"work_{work_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Fetch from API
        try:
            work = self.client.get_work(work_id)
            self._cache[cache_key] = work
            return work
        except Exception as e:
            logging.error(f"Error fetching work {work_id}: {str(e)}")
            raise

    def get_authors(
        self, openalex_ids: List[str]
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Get multiple authors by their IDs.

        Args:
            openalex_ids: List of OpenAlex author IDs

        Returns:
            Tuple containing:
              - List of author data dictionaries
              - Optional cursor for pagination
        """
        # Generate a cache key for this batch
        cache_key = f"authors_{'_'.join(sorted(openalex_ids))}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            authors, cursor = self.client.get_authors(openalex_ids=openalex_ids)
            self._cache[cache_key] = (authors, cursor)
            return authors, cursor
        except Exception as e:
            logging.error(f"Error fetching authors {openalex_ids}: {str(e)}")
            raise

    def get_authors_for_work(self, work: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get detailed author information for all authors in a work.

        This method extracts author IDs from the work and fetches detailed author data.

        Args:
            work: The work dictionary from OpenAlex

        Returns:
            List of detailed author data dictionaries
        """
        # Extract author IDs from work
        author_ids = []
        for authorship in work.get("authorships", []):
            author_id = authorship.get("author", {}).get("id")
            if author_id:
                if "/" in author_id:
                    author_id = author_id.split("/")[-1]
                author_ids.append(author_id)

        # Fetch authors in batches
        if not author_ids:
            return []

        authors, _ = self.get_authors(author_ids)
        return authors

    def build_paper_from_work(
        self, work: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Convert an OpenAlex work to a ResearchHub paper format.

        Args:
            work: The work dictionary from OpenAlex

        Returns:
            Tuple containing:
              - Dictionary with paper data
              - List of concept dictionaries
              - List of topic dictionaries
        """
        return self.client.build_paper_from_openalex_work(work)
