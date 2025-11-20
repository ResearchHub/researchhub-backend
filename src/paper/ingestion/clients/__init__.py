"""
Client modules for fetching papers from various sources.
"""

from .base import BaseClient, ClientConfig
from .chemrxiv import ChemRxivClient, ChemRxivConfig
from .preprints.arxiv import ArXivClient, ArXivConfig
from .preprints.arxiv_oai import ArXivOAIClient, ArXivOAIConfig
from .preprints.biorxiv import BioRxivClient, BioRxivConfig
from .preprints.medrxiv import MedRxivClient, MedRxivConfig

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
