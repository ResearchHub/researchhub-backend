"""
MedRxiv API client for fetching papers.

Inherits from BioRxivBaseClient with MedRxiv-specific configuration.
"""

from typing import Optional

from .biorxiv_base import BioRxivBaseClient, BioRxivBaseConfig


class MedRxivConfig(BioRxivBaseConfig):
    """MedRxiv-specific configuration."""

    def __init__(self, **kwargs):
        defaults = {
            "source_name": "medrxiv",
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class MedRxivClient(BioRxivBaseClient):
    """Client for fetching papers from MedRxiv."""

    default_server = "medrxiv"

    def __init__(self, config: Optional[MedRxivConfig] = None):
        """Initialize MedRxiv client."""
        if config is None:
            config = MedRxivConfig()
        super().__init__(config)
