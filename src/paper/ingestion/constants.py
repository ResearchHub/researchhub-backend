from enum import Enum


class IngestionSource(Enum):
    """Supported ingestion sources."""

    ARXIV = "arxiv"
    BIORXIV = "biorxiv"
    CHEMRXIV = "chemrxiv"
    MEDRXIV = "medrxiv"
