"""
Command for running the paper ingestion pipeline.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from paper.ingestion.clients.arxiv import ArXivClient, ArXivConfig
from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig
from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
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
        parser.add_argument(
            "--since",
            type=str,
            help="Start date for fetching papers (format: YYYY-MM-DD)",
        )
        parser.add_argument(
            "--until",
            type=str,
            help="End date for fetching papers (format: YYYY-MM-DD)",
        )

    def handle(self, *args, **options):
        source = options["source"]
        since_str = options.get("since")
        until_str = options.get("until")

        # Parse date parameters
        since_dt = None
        until_dt = None

        if since_str:
            since_date = parse_date(since_str)
            if since_date:
                # Use start of day
                since_dt = datetime.combine(since_date, datetime.min.time())
            else:
                raise CommandError(f"Invalid date format for 'since': {since_str}.")

        if until_str:
            until_date = parse_date(until_str)
            if until_date:
                # Use end of day
                until_dt = datetime.combine(until_date, datetime.max.time())
            else:
                raise CommandError(f"Invalid date format for 'until': {until_str}.")

        if since_dt and until_dt and since_dt >= until_dt:
            raise CommandError("'since' date must be before 'until' date")

        clients = self._get_clients(source)

        pipeline = PaperIngestionPipeline(clients)

        sources = list(clients.keys()) if source == "all" else [source]

        date_range_msg = ""
        if since_dt:
            date_range_msg += f" from {since_dt}"
        if until_dt:
            date_range_msg += f" until {until_dt}"

        self.stdout.write(
            f"Starting ingestion for: {', '.join(sources)}{date_range_msg}"
        )

        results = pipeline.run_ingestion(
            sources=sources,
            since=since_dt,
            until=until_dt,
        )

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

        return clients
