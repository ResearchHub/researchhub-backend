import logging
from datetime import datetime, timedelta

from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig
from researchhub.celery import app
from utils.sentry import log_error

logger = logging.getLogger(__name__)


@app.task
def pull_biorxiv_papers():
    """
    Temporary task for testing the bioRxiv client for pulling papers.
    """
    config = BioRxivConfig(
        rate_limit=1.0,
        page_size=100,
        request_timeout=60.0,
        max_retries=3,
    )
    client = BioRxivClient(config=config)

    try:
        until = datetime.now()
        since = until - timedelta(days=1)
        logger.info(f"Starting to pull papers from bioRxiv from {since} to {until}")

        papers = client.fetch_recent(since=since, until=until)

        logger.info(f"Fetched {len(papers)} papers from bioRxiv.")
    except Exception as e:
        log_error(e, message="Error fetching papers from bioRxiv")
        logger.error(f"Error fetching papers from bioRxiv: {e}")
