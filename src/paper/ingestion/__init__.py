"""
Paper ingestion module for fetching and processing papers from various sources.

This module provides a unified interface for ingesting papers from multiple
preprint servers and academic repositories.
"""

from .clients import (
    ArXivClient,
    ArXivConfig,
    ArXivOAIClient,
    ArXivOAIConfig,
    BaseClient,
    BioRxivClient,
    BioRxivConfig,
    ClientConfig,
)
from .exceptions import *
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
    # Exceptions (from .exceptions import *)
]
