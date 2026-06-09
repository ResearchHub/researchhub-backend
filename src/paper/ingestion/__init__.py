"""
Paper ingestion module for fetching and processing papers from various sources.

This module provides a unified interface for ingesting papers from multiple
preprint servers and academic repositories.
"""

from .clients.base import BaseClient, ClientConfig
from .clients.preprints.arxiv import ArXivClient, ArXivConfig
from .clients.preprints.arxiv_oai import ArXivOAIClient, ArXivOAIConfig
from .clients.preprints.biorxiv import BioRxivClient, BioRxivConfig
from .exceptions import (
    ClientError,
    FetchError,
    IngestionError,
    RetryExhaustedError,
    TimeoutError,
    ValidationError,
)
from .mappers import BaseMapper, BioRxivMapper

__all__ = [
    # Base classes
    "BaseClient",
    "BaseMapper",
    "ClientConfig",
    # ArXiv implementation
    "ArXivClient",
    "ArXivConfig",
    # ArXiv OAI implementation
    "ArXivOAIClient",
    "ArXivOAIConfig",
    # BioRxiv implementation
    "BioRxivClient",
    "BioRxivConfig",
    "BioRxivMapper",
    # Exceptions
    "ClientError",
    "FetchError",
    "IngestionError",
    "RetryExhaustedError",
    "TimeoutError",
    "ValidationError",
]
