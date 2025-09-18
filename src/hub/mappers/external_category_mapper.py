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
        mappings = cls._get_mappings_for_source(source)
        if _source_category not in mappings:
            if _source_category:  # Incoming category is not mapped
                logger.warning(
                    f"No mapping defined for {source} category: {source_category}"
                )
            return []

        # Get hub names and convert to Hub objects
        hub_names = mappings[_source_category]
        return cls._get_hubs_from_names(hub_names, source_category)

    @classmethod
    def _get_mappings_for_source(cls, source: str):
        """Get the appropriate mapping dictionary for the given source."""
        if source not in cls.MAPPINGS:
            logger.warning(f"Unknown source: {source}. Using arxiv.")
            return cls.MAPPINGS["arxiv"]
        return cls.MAPPINGS[source]

    @classmethod
    def _get_hubs_from_names(cls, hub_names: tuple, source_category: str) -> List[Hub]:
        """Convert hub names to Hub objects."""
        hubs = []

        for hub_name in hub_names:
            if not hub_name:  # Skip None/empty values
                continue

            try:
                hub = Hub.objects.get(name__iexact=hub_name)
                hubs.append(hub)
            except Hub.DoesNotExist:
                logger.warning(
                    "Hub not found in database: %s (for %s)",
                    hub_name,
                    source_category,
                )
            except Hub.MultipleObjectsReturned:
                logger.warning(
                    "Multiple hubs found with name: %s (for %s)",
                    hub_name,
                    source_category,
                )
                # Get the first one
                hub = Hub.objects.filter(name__iexact=hub_name).first()
                if hub:
                    hubs.append(hub)

        return hubs
