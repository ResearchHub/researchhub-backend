"""
Mapper for external category systems (arXiv, bioRxiv) to hubs.
"""

import logging
from functools import lru_cache
from typing import Dict, Optional

from hub.models import Hub

from .arxiv_mappings import ARXIV_MAPPINGS
from .biorxiv_mappings import BIORXIV_MAPPINGS
from .hub_mapping import HubMapping

logger = logging.getLogger(__name__)


class ExternalCategoryMapper:
    """Maps external categories from arXiv and bioRxiv to Hub entities."""

    # Cache for hub lookups (populated on first use)
    _hub_cache: Optional[Dict[str, Hub]] = None
    _mapping_cache: Dict[str, HubMapping] = {}

    @classmethod
    def initialize_hub_cache(cls, force_refresh: bool = False) -> None:
        """
        Load all hubs from database into memory cache.
        """
        if cls._hub_cache is not None and not force_refresh:
            return

        cls._hub_cache = {}

        # Load all hubs
        hubs = Hub.objects.all().select_related("category_id")

        for hub in hubs:
            # Cache by name and namespace
            if hub.namespace == "category":
                cls._hub_cache[f"category:{hub.name.lower()}"] = hub
            elif hub.namespace == "subcategory" and hub.category_id:
                # Cache subcategory with parent category name
                key = f"subcategory:{hub.category_id.name.lower()}:{hub.name.lower()}"
                cls._hub_cache[key] = hub

        logger.info(f"Initialized hub cache with {len(cls._hub_cache)} entries")

    @classmethod
    @lru_cache(maxsize=1024)
    def map(cls, external_category: str, source: str = "arxiv") -> HubMapping:
        """
        Map an external category to Hub entities.

        Args:
            external_category: The external category string (e.g., "cs.AI", "neuroscience")
            source: The source - "arxiv" or "biorxiv"

        Returns:
            HubMapping containing the category and/or subcategory hubs.
            May return partial mapping if some hubs are not found.
        """
        # Ensure cache is initialized
        if cls._hub_cache is None:
            cls.initialize_hub_cache()

        # Check mapping cache first
        cache_key = f"{source}:{external_category.lower()}"
        if cache_key in cls._mapping_cache:
            return cls._mapping_cache[cache_key]

        # Normalize the category
        normalized = external_category.strip().lower()

        # Get the appropriate mapping based on source
        if source == "arxiv":
            mappings = ARXIV_MAPPINGS
        elif source == "biorxiv":
            mappings = BIORXIV_MAPPINGS
        else:
            logger.warning(f"Unknown source: {source}. Using arxiv.")
            mappings = ARXIV_MAPPINGS

        # Look up the hub names from our mapping
        if normalized not in mappings:
            logger.warning(
                f"No mapping defined for {source} category: {external_category}"
            )
            return HubMapping()

        category_name, subcategory_name = mappings[normalized]

        # Get category hub
        category_hub = cls._hub_cache.get(f"category:{category_name.lower()}")
        if not category_hub:
            logger.warning(
                "Category hub not found in database: %s (for %s)",
                category_name,
                external_category,
            )

        # Get subcategory hub if specified
        subcategory_hub = None
        if subcategory_name and category_hub:
            subcategory_key = (
                f"subcategory:{category_name.lower()}:{subcategory_name.lower()}"
            )
            subcategory_hub = cls._hub_cache.get(subcategory_key)

            if not subcategory_hub:
                logger.warning(
                    "Subcategory hub not found in database: %s (for %s)",
                    subcategory_name,
                    external_category,
                )

        # Create the mapping
        mapping = HubMapping(category_hub, subcategory_hub)

        # Cache the result
        cls._mapping_cache[cache_key] = mapping

        return mapping


# Backward compatibility alias
HubToCategoryMapper = ExternalCategoryMapper
