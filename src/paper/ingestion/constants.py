from enum import Enum


class IngestionSource(Enum):
    """Supported ingestion sources."""

    ARXIV = "arxiv"
    ARXIV_OAIPMH = "arxiv_oaipmh"
    BIORXIV = "biorxiv"
    CHEMRXIV = "chemrxiv"
    MEDRXIV = "medrxiv"
    OPENALEX = "openalex"
