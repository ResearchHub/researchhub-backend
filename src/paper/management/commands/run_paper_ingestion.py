"""
Command for running the paper ingestion pipeline.
"""

from django.core.management.base import BaseCommand

from paper.ingestion.clients.arxiv import ArXivClient, ArXivConfig
from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig
from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
from paper.ingestion.clients.medrxiv import MedRxivClient, MedRxivConfig
from paper.ingestion.pipeline import PaperIngestionPipeline


class Command(BaseCommand):
    help = "Run paper ingestion pipeline"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            choices=["arxiv", "biorxiv", "chemrxiv", "medrxiv", "all"],
            default="all",
            help="Source to fetch papers from (default: all)",
        )

    def handle(self, *args, **options):
        source = options["source"]

        clients = self._get_clients(source)

        pipeline = PaperIngestionPipeline(clients)

        sources = list(clients.keys()) if source == "all" else [source]

        self.stdout.write(f"Starting ingestion for: {', '.join(sources)}")

        results = pipeline.run_ingestion(sources=sources)

        for src, status in results.items():
            self.stdout.write(f"\n{src}:")
            self.stdout.write(f"  Fetched: {status.total_fetched}")
            self.stdout.write(f"  Created: {status.total_created}")
            self.stdout.write(f"  Updated: {status.total_updated}")
            self.stdout.write(f"  Errors: {status.total_errors}")

    def _get_clients(self, source):
        """
        Client factory to instantiate clients based on the given source argument.
        """
        clients = {}

        if source in ["arxiv", "all"]:
            clients["arxiv"] = ArXivClient(
                ArXivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )

        if source in ["biorxiv", "all"]:
            clients["biorxiv"] = BioRxivClient(
                BioRxivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )

        if source in ["chemrxiv", "all"]:
            clients["chemrxiv"] = ChemRxivClient(
                ChemRxivConfig(
                    rate_limit=0.5,
                    page_size=50,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )

        if source in ["medrxiv", "all"]:
            clients["medrxiv"] = MedRxivClient(
                MedRxivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )

        return clients
