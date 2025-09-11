"""
Mapper for external category systems (arXiv, bioRxiv) to hubs.
"""

import logging

from hub.models import Hub, HubCategory

from .arxiv_mappings import ARXIV_MAPPINGS
from .biorxiv_mappings import BIORXIV_MAPPINGS
from .chemrxiv_mappings import CHEMRXIV_MAPPINGS
from .hub_mapping import HubMapping
from .medrxiv_mappings import MEDRXIV_MAPPINGS

logger = logging.getLogger(__name__)


class ExternalCategoryMapper:
    """Maps external categories from arXiv and bioRxiv to Hub entities."""

    @classmethod
    def map(cls, external_category: str, source: str = "arxiv") -> HubMapping:
        """
        Map an external category to HubCategory and Hub entities.

        Args:
            external_category: The external category string (e.g., "cs.AI")
            source: The source - "arxiv", "biorxiv", "medrxiv", or "chemrxiv"

        Returns:
            HubMapping containing the HubCategory and/or subcategory hub.
            May return partial mapping if some entities are not found.
        """
        # Normalize the category
        normalized = external_category.strip().lower()

        # Get the appropriate mapping based on source
        if source == "arxiv":
            mappings = ARXIV_MAPPINGS
        elif source == "biorxiv":
            mappings = BIORXIV_MAPPINGS
        elif source == "medrxiv":
            mappings = MEDRXIV_MAPPINGS
        elif source == "chemrxiv":
            mappings = CHEMRXIV_MAPPINGS
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

        # Get HubCategory from database
        hub_category = None
        try:
            hub_category = HubCategory.objects.get(category_name__iexact=category_name)
        except HubCategory.DoesNotExist:
            logger.warning(
                "HubCategory not found in database: %s (for %s)",
                category_name,
                external_category,
            )

        # Get subcategory hub if specified
        subcategory_hub = None
        if subcategory_name and hub_category:
            try:
                subcategory_hub = Hub.objects.get(
                    name__iexact=subcategory_name,
                    namespace="subcategory",
                    category=hub_category,
                )
            except Hub.DoesNotExist:
                logger.warning(
                    "Subcategory hub not found in database: %s (for %s)",
                    subcategory_name,
                    external_category,
                )
            except Hub.MultipleObjectsReturned:
                logger.warning(
                    "Multiple subcategory hubs found: %s (for %s)",
                    subcategory_name,
                    external_category,
                )
                # Get the first one
                subcategory_hub = Hub.objects.filter(
                    name__iexact=subcategory_name,
                    namespace="subcategory",
                    category=hub_category,
                ).first()

        # Create the mapping
        return HubMapping(hub_category, subcategory_hub)
