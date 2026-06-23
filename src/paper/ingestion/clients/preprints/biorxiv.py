"""
BioRxiv API client for fetching papers.

Inherits from BioRxivBaseClient with BioRxiv-specific configuration.
"""

from .biorxiv_base import BioRxivBaseClient, BioRxivBaseConfig


class BioRxivConfig(BioRxivBaseConfig):
    """BioRxiv-specific configuration."""

    def __init__(self, **kwargs):
        defaults = {
            "source_name": "biorxiv",
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


class BioRxivClient(BioRxivBaseClient):
    """Client for fetching papers from BioRxiv."""

    default_server = "biorxiv"

    def __init__(self, config: BioRxivConfig | None = None):
        """Initialize BioRxiv client."""
        if config is None:
            config = BioRxivConfig()
        super().__init__(config)
