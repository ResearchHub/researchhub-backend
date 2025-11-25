"""
Client modules for fetching papers from various sources.
"""

from .base import BaseClient, ClientConfig
from .enrichment.altmetric import AltmetricClient
from .enrichment.bluesky import BlueskyClient, BlueskyMetricsClient
from .enrichment.github import GithubClient, GithubMetricsClient
from .enrichment.openalex import OpenAlexClient
from .preprints.arxiv import ArXivClient, ArXivConfig
from .preprints.arxiv_oai import ArXivOAIClient, ArXivOAIConfig
from .preprints.biorxiv import BioRxivClient, BioRxivConfig
from .preprints.chemrxiv import ChemRxivClient, ChemRxivConfig
from .preprints.medrxiv import MedRxivClient, MedRxivConfig

__all__ = [
    "AltmetricClient",
    "ArXivClient",
    "ArXivConfig",
    "ArXivOAIClient",
    "ArXivOAIConfig",
    "BaseClient",
    "BioRxivClient",
    "BioRxivConfig",
    "BlueskyClient",
    "BlueskyMetricsClient",
    "ChemRxivClient",
    "ChemRxivConfig",
    "ClientConfig",
    "GithubClient",
    "GithubMetricsClient",
    "MedRxivClient",
    "MedRxivConfig",
    "OpenAlexClient",
]
