"""
Client modules for fetching papers from various sources.
"""

from .arxiv import ArXivClient, ArXivConfig
from .arxiv_oai import ArXivOAIClient, ArXivOAIConfig
from .base import BaseClient, ClientConfig
from .biorxiv import BioRxivClient, BioRxivConfig
from .chemrxiv import ChemRxivClient, ChemRxivConfig
from .medrxiv import MedRxivClient, MedRxivConfig

__all__ = [
    "ArXivClient",
    "ArXivConfig",
    "ArXivOAIClient",
    "ArXivOAIConfig",
    "BaseClient",
    "BioRxivClient",
    "BioRxivConfig",
    "ChemRxivClient",
    "ChemRxivConfig",
    "ClientConfig",
    "MedRxivClient",
    "MedRxivConfig",
]
