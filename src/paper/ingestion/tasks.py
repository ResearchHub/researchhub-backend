import logging
from datetime import datetime, timedelta

from paper.ingestion.clients.arxiv import ArXivClient, ArXivConfig
from paper.ingestion.clients.biorxiv import BioRxivClient, BioRxivConfig
from paper.ingestion.clients.chemrxiv import ChemRxivClient, ChemRxivConfig
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


@app.task
def pull_papers_with_cursor(source="biorxiv", cursor=None, since=None, until=None):
    """
    Example task demonstrating cursor-based pagination for pulling papers.

    Args:
        source: Paper source ("biorxiv", "arxiv", "chemrxiv")
        cursor: Cursor from previous request (None for first page)
        since: Start date as ISO string (e.g., "2025-01-01")
        until: End date as ISO string

    Returns:
        dict with papers and next cursor
    """
    # Parse dates if provided
    if since:
        since = datetime.fromisoformat(since)
    if until:
        until = datetime.fromisoformat(until)

    # Select client based on source
    if source == "biorxiv":
        config = BioRxivConfig(
            rate_limit=1.0,
            page_size=100,
            request_timeout=60.0,
        )
        client = BioRxivClient(config=config)
    elif source == "arxiv":
        config = ArXivConfig(
            rate_limit=0.33,
            page_size=100,
            request_timeout=30.0,
        )
        client = ArXivClient(config=config)
    elif source == "chemrxiv":
        config = ChemRxivConfig(
            rate_limit=1.0,
            page_size=100,
            request_timeout=30.0,
        )
        client = ChemRxivClient(config=config)
    else:
        raise ValueError(f"Unknown source: {source}")

    try:
        logger.info(
            f"Fetching papers from {source} with cursor={cursor}, "
            f"since={since}, until={until}"
        )

        # Fetch a single page using cursor
        response = client.fetch_page(
            cursor=cursor,
            since=since,
            until=until,
        )

        logger.info(
            f"Fetched {len(response.data)} papers from {source}. "
            f"Has more: {response.has_more}, Next cursor: {response.cursor}"
        )

        return {
            "papers": response.data,
            "cursor": response.cursor,
            "has_more": response.has_more,
            "total": response.total,
        }

    except Exception as e:
        log_error(e, message=f"Error fetching papers from {source}")
        logger.error(f"Error fetching papers from {source}: {e}")
        raise


@app.task
def pull_all_papers_paginated(source="biorxiv", since=None, until=None, max_pages=10):
    """
    Example task demonstrating how to fetch multiple pages using cursors.

    Args:
        source: Paper source
        since: Start date as ISO string
        until: End date as ISO string
        max_pages: Maximum number of pages to fetch

    Returns:
        List of all papers fetched
    """
    all_papers = []
    cursor = None
    pages_fetched = 0

    while pages_fetched < max_pages:
        result = pull_papers_with_cursor.apply_async(
            args=[source],
            kwargs={
                "cursor": cursor,
                "since": since,
                "until": until,
            },
        ).get()

        all_papers.extend(result["papers"])
        pages_fetched += 1

        if not result["has_more"] or result["cursor"] is None:
            logger.info(f"No more pages available. Fetched {pages_fetched} pages.")
            break

        cursor = result["cursor"]
        logger.info(f"Fetched page {pages_fetched}, moving to next page...")

    logger.info(f"Total papers fetched: {len(all_papers)} across {pages_fetched} pages")
    return all_papers
