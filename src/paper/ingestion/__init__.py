"""
Paper ingestion module for fetching and processing papers from various sources.

This module provides a unified interface for ingesting papers from multiple
preprint servers and academic repositories.
"""

from .clients import BaseClient, BioRxivClient, BioRxivConfig, ClientConfig
from .exceptions import *
from .mappers import BaseMapper, BioRxivMapper

__version__ = "0.1.0"

__all__ = [
    # Base classes
    "ClientConfig",
    "BaseClient",
    "BaseMapper",
    "Base",  # Legacy compatibility
    # BioRxiv implementation
    "BioRxivClient",
    "BioRxivConfig",
    "BioRxivMapper",
    # Exceptions (from .exceptions import *)
]
