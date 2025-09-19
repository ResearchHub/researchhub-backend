"""
Mapper for external category systems (arXiv, bioRxiv, ChemRxiv, MedRxiv) to hubs.
"""

import logging
from typing import List

from hub.models import Hub

from .arxiv_mappings import ARXIV_MAPPINGS
from .biorxiv_mappings import BIORXIV_MAPPINGS
from .chemrxiv_mappings import CHEMRXIV_MAPPINGS
from .medrxiv_mappings import MEDRXIV_MAPPINGS

logger = logging.getLogger(__name__)


class ExternalCategoryMapper:
    """Maps external categories from preprint servers to Hub entities."""

    # Mapping sources
    MAPPINGS = {
        "arxiv": ARXIV_MAPPINGS,
        "biorxiv": BIORXIV_MAPPINGS,
        "medrxiv": MEDRXIV_MAPPINGS,
        "chemrxiv": CHEMRXIV_MAPPINGS,
    }

    @classmethod
    def map(cls, source_category: str, source: str = "arxiv") -> List[Hub]:
        """
        Map an external category to a list of Hub entities.

        Args:
            source_category: The external category string (e.g., "cs.AI")
            source: The source - "arxiv", "biorxiv", "medrxiv", or "chemrxiv"

        Returns:
            List of Hub entities that correspond to this external category.
        """
        # Normalize the category
        _source_category = source_category.strip().lower()

        # Get the appropriate mapping
        if source not in cls.MAPPINGS:
            logger.warning(f"Unknown source: {source}. No mappings available.")
            return []

        mappings = cls.MAPPINGS[source]
        if _source_category not in mappings:
            if _source_category:  # Incoming category is not mapped
                logger.warning(
                    f"No mapping defined for {source} category: {source_category}"
                )
            return []

        # Get hub slugs and convert to Hub objects
        hub_slugs = mappings[_source_category]
        return cls._get_hubs_from_slugs(hub_slugs, source_category)

    @classmethod
    def _get_hubs_from_slugs(cls, hub_slugs: tuple, source_category: str) -> List[Hub]:
        """Convert hub slugs to Hub objects."""
        hubs = []

        for hub_slug in hub_slugs:
            if not hub_slug:  # Skip None/empty values
                continue

            try:
                hub = Hub.objects.get(slug=hub_slug)
                hubs.append(hub)
            except Hub.DoesNotExist:
                logger.warning(
                    "Hub not found in database: %s (for %s)",
                    hub_slug,
                    source_category,
                )

        return hubs
