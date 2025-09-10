"""
Mapper for external category systems (arXiv, bioRxiv) to hubs.
"""

import logging
from functools import lru_cache
from typing import Dict, Optional

from hub.models import Hub, HubCategory

from .arxiv_mappings import ARXIV_MAPPINGS
from .biorxiv_mappings import BIORXIV_MAPPINGS
from .hub_mapping import HubMapping

logger = logging.getLogger(__name__)


class ExternalCategoryMapper:
    """Maps external categories from arXiv and bioRxiv to Hub entities."""

    # Cache for lookups (populated on first use)
    _hub_cache: Optional[Dict[str, Hub]] = None
    _hub_category_cache: Optional[Dict[str, HubCategory]] = None
    _mapping_cache: Dict[str, HubMapping] = {}

    @classmethod
    def initialize_hub_cache(cls, force_refresh: bool = False) -> None:
        """
        Load all hubs and hub categories from database into memory cache.
        """
        cache_already_initialized = (
            cls._hub_cache is not None and cls._hub_category_cache is not None
        )

        if cache_already_initialized and not force_refresh:
            return

        cls._hub_cache = {}
        cls._hub_category_cache = {}

        # Load all HubCategories
        hub_categories = HubCategory.objects.all()
        for hub_cat in hub_categories:
            cls._hub_category_cache[hub_cat.category_name.lower()] = hub_cat

        # Load all subcategory hubs
        hubs = Hub.objects.filter(namespace="subcategory").select_related("category")

        for hub in hubs:
            # Cache subcategory with parent category name
            if hub.category:
                key = (
                    f"subcategory:{hub.category.category_name.lower()}:"
                    f"{hub.name.lower()}"
                )
                cls._hub_cache[key] = hub

        logger.info(
            f"Initialized cache with {len(cls._hub_category_cache)} categories "
            f"and {len(cls._hub_cache)} subcategory hubs"
        )

    @classmethod
    @lru_cache(maxsize=1024)
    def map(cls, external_category: str, source: str = "arxiv") -> HubMapping:
        """
        Map an external category to HubCategory and Hub entities.

        Args:
            external_category: The external category string (e.g., "cs.AI")
            source: The source - "arxiv" or "biorxiv"

        Returns:
            HubMapping containing the HubCategory and/or subcategory hub.
            May return partial mapping if some entities are not found.
        """
        # Ensure cache is initialized
        if cls._hub_cache is None or cls._hub_category_cache is None:
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

        # Get HubCategory
        hub_category = cls._hub_category_cache.get(category_name.lower())
        if not hub_category:
            logger.warning(
                "HubCategory not found in database: %s (for %s)",
                category_name,
                external_category,
            )

        # Get subcategory hub if specified
        subcategory_hub = None
        if subcategory_name and hub_category:
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
        mapping = HubMapping(hub_category, subcategory_hub)

        # Cache the result
        cls._mapping_cache[cache_key] = mapping

        return mapping

    @classmethod
    def clear_cache(cls):
        """Clear all caches."""
        cls._hub_cache = None
        cls._hub_category_cache = None
        cls._mapping_cache = {}
        cls.map.cache_clear()
