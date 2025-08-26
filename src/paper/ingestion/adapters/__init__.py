"""Source-specific adapters for paper ingestion"""

from .arxiv_adapter import ArxivAdapter
from .biorxiv_adapter import BiorxivMedrxivAdapter
from .pubmed_adapter import PubmedAdapter

__all__ = [
    "ArxivAdapter",
    "BiorxivMedrxivAdapter",
    "PubmedAdapter",
]
