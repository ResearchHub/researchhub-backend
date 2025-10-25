"""
Client modules for fetching papers from various sources.
"""

from .arxiv import ArXivClient, ArXivConfig
from .arxiv_oaipmh import ArXivOAIPMHClient, ArXivOAIPMHConfig
from .base import BaseClient, ClientConfig
from .biorxiv import BioRxivClient, BioRxivConfig
from .chemrxiv import ChemRxivClient, ChemRxivConfig
from .medrxiv import MedRxivClient, MedRxivConfig

__all__ = [
    "ArXivClient",
    "ArXivConfig",
    "ArXivOAIPMHClient",
    "ArXivOAIPMHConfig",
    "BaseClient",
    "BioRxivClient",
    "BioRxivConfig",
    "ChemRxivClient",
    "ChemRxivConfig",
    "ClientConfig",
    "MedRxivClient",
    "MedRxivConfig",
]
