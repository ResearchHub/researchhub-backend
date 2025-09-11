"""
Client modules for fetching papers from various sources.
"""

from .arxiv import ArXivClient, ArXivConfig
from .base import BaseClient, ClientConfig
from .biorxiv import BioRxivClient, BioRxivConfig
from .chemrxiv import ChemRxivClient, ChemRxivConfig

__all__ = [
    "ArXivClient",
    "ArXivConfig",
    "BaseClient",
    "BioRxivClient",
    "BioRxivConfig",
    "ChemRxivClient",
    "ChemRxivConfig",
    "ClientConfig",
]
