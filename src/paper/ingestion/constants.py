from enum import Enum


class IngestionSource(Enum):
    """Supported ingestion sources."""

    ARXIV = "arxiv"
    ARXIV_OAI = "arxiv_oai"
    BIORXIV = "biorxiv"
    CHEMRXIV = "chemrxiv"
    MEDRXIV = "medrxiv"
    OPENALEX = "openalex"
