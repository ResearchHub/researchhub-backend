"""
BioRxiv data mapper for transforming API responses to Paper model format.

Inherits from BioRxivBaseMapper with BioRxiv-specific configuration.
"""

from .biorxiv_base import BioRxivBaseMapper


class BioRxivMapper(BioRxivBaseMapper):
    """Maps BioRxiv paper records to ResearchHub Paper model format."""

    # BioRxiv-specific configuration
    default_server = "biorxiv"
    hub_slug = "biorxiv"
