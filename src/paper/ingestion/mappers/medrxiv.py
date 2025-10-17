"""
MedRxiv data mapper for transforming API responses to Paper model format.

Inherits from BioRxivBaseMapper with MedRxiv-specific configuration.
"""

from .biorxiv_base import BioRxivBaseMapper


class MedRxivMapper(BioRxivBaseMapper):
    """Maps MedRxiv paper records to ResearchHub Paper model format."""

    # MedRxiv-specific configuration
    default_server = "medrxiv"
    hub_slug = "medrxiv"
