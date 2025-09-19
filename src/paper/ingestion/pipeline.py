"""
Paper ingestion pipeline for fetching and processing papers from multiple sources.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from celery import group
from django.conf import settings
from django.utils import timezone

from paper.ingestion.clients.arxiv import ArXivClient, ArXivConfig
from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig
from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
from paper.ingestion.exceptions import FetchError, RetryExhaustedError
from paper.ingestion.service import IngestionSource, PaperIngestionService
from paper.models import PaperFetchLog
from researchhub.celery import QUEUE_PULL_PAPERS, app
from utils.sentry import log_error

logger = logging.getLogger(__name__)


@dataclass
class IngestionStatus:
    """
    Represents the status of an ingestion run.
    """

    source: str
    start_time: datetime
    end_time: Optional[datetime] = None
    total_fetched: int = 0
    total_processed: int = 0
    total_created: int = 0
    total_updated: int = 0
    total_errors: int = 0
    errors: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PaperIngestionPipeline:
    """
    Orchestrator for ingesting papers from different preprint servers.
    """

    BATCH_SIZE = 25  # Number of papers to process in each batch

    def __init__(self, clients: Dict[str, Any]):
        self.clients = clients

    def run_ingestion(
        self,
        sources: Optional[List[str]] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> Dict[str, IngestionStatus]:
        """
        Run the ingestion pipeline for specified sources.

        Args:
            sources: List of source names to fetch from. Uses all enabled sources if none provided.
            since: Start date for fetching papers. Uses last successful fetch time if none provided.
            until: End date for fetching papers. Uses current time if none provided.

        Returns:
            Dictionary mapping source names to their ingestion status.
        """
        if sources is None:
            sources = list(self.clients.keys())

        if until is None:
            until = timezone.now()

        results = {}

        for source in sources:
            if source not in self.clients:
                logger.warning(f"Source [{source}] not configured, skipping")
                continue

            # Get the last successful fetch time for this source
            if since is None:
                since = self._get_last_fetch_time(source)

            logger.info(f"Starting ingestion for {source} from {since} to {until}")

            status = IngestionStatus(
                source=source,
                start_time=timezone.now(),
            )

            try:
                # Fetch...
                papers_data = self._fetch_papers(source, since, until, status)
                # ... and process papers in batches.
                self._process_papers_in_batches(source, papers_data)

                status.end_time = timezone.now()
                self._log_fetch(source, status, success=True)
            except Exception as e:
                status.end_time = timezone.now()
                status.errors.append(
                    {
                        "type": "pipeline_error",
                        "message": str(e),
                    }
                )
                logger.error(f"Pipeline error for [{source}]: {e}")
                log_error(e, message=f"Pipeline error for [{source}]")
                # Log failure
                self._log_fetch(source, status, success=False)

            results[source] = status

        return results

    def _fetch_papers(
        self,
        source: str,
        since: datetime,
        until: datetime,
        status: IngestionStatus,
    ) -> List[Dict[str, Any]]:
        """
        Fetch papers from the given source (preprint server).
        """
        client = self.clients[source]
        papers = []

        try:
            papers = client.fetch_recent(since=since, until=until)
            status.total_fetched = len(papers)

            logger.info(f"Fetched {len(papers)} papers from {source}")
        except (FetchError, RetryExhaustedError) as e:
            status.errors.append(
                {
                    "type": "fetch_error",
                    "message": str(e),
                }
            )
            logger.error(f"Failed to fetch papers from {source}: {e}")
            raise

        return papers

    def _process_papers_in_batches(
        self,
        source: str,
        papers_data: List[Dict[str, Any]],
    ) -> None:
        """
        Process papers in batches to avoid blocking the database.
        """
        total_papers = len(papers_data)

        for i in range(0, total_papers, self.BATCH_SIZE):
            batch = papers_data[i : i + self.BATCH_SIZE]
            batch_num = (i // self.BATCH_SIZE) + 1
            total_batches = (total_papers + self.BATCH_SIZE - 1) // self.BATCH_SIZE

            logger.info(
                f"Processing batch {batch_num}/{total_batches} "
                f"({len(batch)} papers) from {source}"
            )

            # Process batches asynchronously
            process_batch_task.delay(source, batch)

    def _get_last_fetch_time(self, source: str) -> datetime:
        """
        Get the last successful fetch time for the given source.
        """
        last_fetch = (
            PaperFetchLog.objects.filter(
                source=source.upper(),
                status=PaperFetchLog.SUCCESS,
            )
            .order_by("-completed_date")
            .first()
        )

        if last_fetch and last_fetch.completed_date:
            return last_fetch.completed_date

        # Default to 1 day ago if no previous fetch
        return timezone.now() - timedelta(days=1)

    def _log_fetch(
        self,
        source: str,
        status: IngestionStatus,
        success: bool,
    ) -> None:
        """
        Log the fetch attempt to the database.
        """
        PaperFetchLog.objects.create(
            source=source.upper(),
            fetch_type=PaperFetchLog.FETCH_UPDATE,
            status=PaperFetchLog.SUCCESS if success else PaperFetchLog.FAILED,
            started_date=status.start_time,
            completed_date=status.end_time,
            total_papers_processed=status.total_fetched,
        )


@app.task(
    queue=QUEUE_PULL_PAPERS,
)
def fetch_all_papers() -> Dict[str, Any]:
    """
    Orchestrator task that triggers parallel fetching from all sources.
    Entry point for scheduling.
    """
    # Check if paper ingestion is enabled
    if not getattr(settings, "PAPER_INGESTION_ENABLED", False):
        logger.info("Paper ingestion is disabled in settings. Skipping.")
        return {}

    sources = ["arxiv", "biorxiv", "chemrxiv"]

    # Create a group of parallel tasks
    job = group(fetch_papers_from_source.s(source) for source in sources)

    # Execute the group
    result = job.delay()

    return {
        "status": "initiated",
        "sources": sources,
        "job_id": result.id,
    }


@app.task(
    queue=QUEUE_PULL_PAPERS,
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def fetch_papers_from_source(
    source: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Task for fetching papers from a specific source.

    Main entry point for scheduled paper fetching.
    """
    try:
        # Initialize the appropriate client for this source
        clients = {}

        if source == "arxiv":
            clients["arxiv"] = ArXivClient(
                ArXivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )
        elif source == "biorxiv":
            clients["biorxiv"] = BioRxivClient(
                BioRxivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )
        elif source == "chemrxiv":
            clients["chemrxiv"] = ChemRxivClient(
                ChemRxivConfig(
                    rate_limit=0.5,
                    page_size=50,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )
        elif source == "medrxiv":
            clients["medrxiv"] = BioRxivClient(
                BioRxivConfig(
                    rate_limit=1.0,
                    page_size=100,
                    request_timeout=60.0,
                    max_retries=3,
                )
            )
        else:
            raise ValueError(f"Unknown source: {source}")

        pipeline = PaperIngestionPipeline(clients)

        since_date = datetime.fromisoformat(since) if since else None
        until_date = datetime.fromisoformat(until) if until else None

        results = pipeline.run_ingestion(
            sources=[source],
            since=since_date,
            until=until_date,
        )

        return results[source].to_dict()

    except Exception as e:
        logger.error(f"Failed to fetch papers from {source}: {e}")
        log_error(e, message=f"Failed to fetch papers from {source}")
        raise  # Let Celery handle the retry


@app.task(
    queue=QUEUE_PULL_PAPERS,
    max_retries=3,
    retry_backoff=True,
    autoretry_for=(Exception,),
)
def process_batch_task(
    source: str,
    batch: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Process a batch of papers and save them to the database.
    """
    service = PaperIngestionService()
    successes, failures = service.ingest_papers(batch, IngestionSource(source))

    return {
        "source": source,
        "batch_size": len(batch),
        "created": len(successes),
        "errors": len(failures),
    }
