from paper.ingestion.clients.base import BaseClient
from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
from paper.ingestion.clients.preprints.arxiv import ArXivClient, ArXivConfig
from paper.ingestion.clients.preprints.arxiv_oai import ArXivOAIClient, ArXivOAIConfig
from paper.ingestion.clients.preprints.biorxiv import BioRxivClient, BioRxivConfig
from paper.ingestion.clients.preprints.medrxiv import MedRxivClient, MedRxivConfig
from paper.ingestion.constants import IngestionSource


class ClientFactory:
    """
    Factory for creating preprint server API client instances with sensible defaults.
    """

    _CLIENTS = {
        IngestionSource.ARXIV: (
            ArXivClient,
            ArXivConfig(
                rate_limit=1.0,
                page_size=25,
                request_timeout=60.0,
                max_retries=3,
            ),
        ),
        IngestionSource.ARXIV_OAI: (
            ArXivOAIClient,
            ArXivOAIConfig(
                rate_limit=0.33,
                page_size=100,
                request_timeout=60.0,
                max_retries=3,
            ),
        ),
        IngestionSource.BIORXIV: (
            BioRxivClient,
            BioRxivConfig(
                rate_limit=1.0,
                page_size=100,
                request_timeout=60.0,
                max_retries=3,
            ),
        ),
        IngestionSource.CHEMRXIV: (
            ChemRxivClient,
            ChemRxivConfig(
                rate_limit=0.5,
                page_size=50,
                request_timeout=60.0,
                max_retries=3,
            ),
        ),
        IngestionSource.MEDRXIV: (
            MedRxivClient,
            MedRxivConfig(
                rate_limit=1.0,
                page_size=100,
                request_timeout=60.0,
                max_retries=3,
            ),
        ),
    }

    @staticmethod
    def create_client(source: IngestionSource) -> BaseClient:
        """
        Create a single client instance for the given source.

        Args:
            source: The ingestion source.

        Returns:
            Client instance for the source.

        Raises:
            ValueError: If the source is not supported.
        """
        if source not in ClientFactory._CLIENTS:
            raise ValueError(f"Unknown source: {source}")

        client_class, config = ClientFactory._CLIENTS[source]
        return client_class(config)
