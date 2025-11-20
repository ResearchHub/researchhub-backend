"""
Client modules for fetching papers from various sources.
"""

from .base import BaseClient, ClientConfig
from .biorxiv import BioRxivClient, BioRxivConfig
from .chemrxiv import ChemRxivClient, ChemRxivConfig
from .medrxiv import MedRxivClient, MedRxivConfig
from .preprints.arxiv import ArXivClient, ArXivConfig
from .preprints.arxiv_oai import ArXivOAIClient, ArXivOAIConfig

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
