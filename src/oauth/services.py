import logging
import re
from typing import List

from django.core.cache import cache
from django.db import transaction

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tasks import download_pdf
from user.models import Author
from utils.openalex import OpenAlex
from utils.orcid import get_orcid_account_and_token, list_user_dois


@transaction.atomic
def sync_orcid_for_user(user) -> None:
    """
    Pull ORCID works for the given user and merge into our Paper records.

    All database operations are wrapped in a transaction for data integrity.

    Steps:
    1) Read DOIs (plus optional title/abstract) from ORCID.
    2) Query OpenAlex for each DOI to get canonical work records.
    3) Pass works through our OpenAlex ingestion pipeline.
    4) Overlay missing title/abstract from ORCID values when OpenAlex lacks them,
       recompute completeness, and enqueue a PDF download if needed.
    5) Create authorship relationships.

    Note: All database operations are atomic - if any step fails,
    all changes will be rolled back.
    """
    account, token = get_orcid_account_and_token(user, auto_refresh=True)
    if not (account and token and token.token):
        return

    orcid_id = account.uid
    logger = logging.getLogger(__name__)

    logger.info(f"Starting ORCID sync for user {user.id} (with transaction)")

    # Validate token scope
    if not token.token:
        logger.error("Access token is None or empty!")
        return

    scope = (account.extra_data or {}).get("scope")
    if scope and "/read-limited" not in scope and "/authenticate" not in scope:
        logger.warning(
            f"Token may not have required scope. Current: {scope}, "
            f"Required: /read-limited or /authenticate"
        )
    elif scope and "/read-limited" not in scope:
        logger.info(
            f"Token has /authenticate scope but not /read-limited. "
            f"Limited data access may be restricted. Current scope: {scope}"
        )

    # 1) Pull DOIs from ORCID - OPTIMIZED
    try:
        orcid_items = list_user_dois(token.token, orcid_id)
        if not orcid_items:
            return

        # Process DOIs more efficiently with dict comprehension and filtering
        valid_items = [
            (item, _normalize_doi(item.get("doi")))
            for item in orcid_items
            if item.get("doi") and _normalize_doi(item.get("doi"))
        ]

        if not valid_items:
            return

        # Use sets for faster lookups and list comprehension for performance
        dois = [doi for _, doi in valid_items]
        by_doi = {
            doi: {
                "title": item.get("title"),
                "abstract": item.get("abstract"),
            }
            for item, doi in valid_items
        }
    except Exception as e:
        logger.error(f"Failed to fetch ORCID works for user {user.id}: {e}")
        return

    # 2) Fetch OpenAlex works and process them - OPTIMIZED
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def fetch_openalex_work(doi):
        """Fetch single work from OpenAlex with error handling."""
        try:
            return OpenAlex().get_data_from_doi(doi)
        except Exception:
            return None  # Ignore DOIs OpenAlex can't resolve

    # Process OpenAlex API calls concurrently for better performance
    works = []
    if dois:
        # Limit concurrent requests to avoid overwhelming the API
        max_workers = min(len(dois), 10)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all requests
            future_to_doi = {
                executor.submit(fetch_openalex_work, doi): doi for doi in dois
            }

            # Collect results as they complete
            for future in as_completed(future_to_doi):
                work = future.result()
                if work:
                    works.append(work)

    if works:
        process_openalex_works(works)

    # 3) Overlay missing data and trigger PDF downloads - OPTIMIZED
    # Bulk fetch all papers by DOI to reduce database queries
    # Use case-insensitive matching for each DOI individually
    papers_qs = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    ).only("id", "doi", "title", "abstract", "completeness", "file", "pdf_url", "url")

    papers_by_doi = {paper.doi.lower(): paper for paper in papers_qs}

    papers_to_update = []
    pdf_download_ids = []
    for doi in dois:
        paper = papers_by_doi.get(doi.lower())
        if not paper:
            continue

        # Fill missing title/abstract from ORCID
        overlay = by_doi.get(doi, {})
        dirty_fields = []

        if not paper.title and overlay.get("title"):
            paper.title = overlay["title"]
            dirty_fields.append("title")

        if not paper.abstract and overlay.get("abstract"):
            paper.abstract = overlay["abstract"]
            dirty_fields.append("abstract")

        if dirty_fields:
            paper.set_paper_completeness()
            dirty_fields.append("completeness")
            papers_to_update.append((paper, dirty_fields))

        # Collect PDF download IDs for batch processing
        if not paper.file and (paper.pdf_url or paper.url):
            pdf_download_ids.append(paper.id)
    # Bulk update papers that need changes
    for paper, dirty_fields in papers_to_update:
        paper.save(update_fields=dirty_fields)

    # Batch trigger PDF downloads
    for paper_id in pdf_download_ids:
        download_pdf.delay(paper_id)

    # Create authorship relationships
    _create_orcid_authorships(user, dois)

    logger.info(
        f"Successfully completed ORCID sync for user {user.id} "
        f"(transaction committed)"
    )


def _create_orcid_authorships(user, dois: List[str]) -> None:
    """Create authorship relationships for ORCID user and papers - OPTIMIZED."""
    try:
        author = Author.objects.get(user=user)
    except Author.DoesNotExist:
        logging.getLogger(__name__).warning(
            f"No Author profile found for user {user.id}"
        )
        return

    # Bulk fetch papers and existing authorships to minimize queries
    # Use case-insensitive matching for DOIs
    papers_qs = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    ).only("id", "doi")

    papers_by_doi = {paper.doi.lower(): paper for paper in papers_qs}

    # Get existing authorship paper IDs to avoid duplicates
    existing_paper_ids = set(
        Authorship.objects.filter(
            author=author,
            paper__doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$",
        ).values_list("paper_id", flat=True)
    )

    # Prepare bulk create list
    authorships_to_create = []
    raw_author_name = f"{author.first_name} {author.last_name}".strip()
    for doi in dois:
        paper = papers_by_doi.get(doi.lower())
        if paper and paper.id not in existing_paper_ids:
            authorships_to_create.append(
                Authorship(
                    author=author,
                    paper=paper,
                    author_position="middle",
                    is_corresponding=False,
                    raw_author_name=raw_author_name,
                )
            )

    # Bulk create authorships
    if authorships_to_create:
        Authorship.objects.bulk_create(authorships_to_create, ignore_conflicts=True)
        cache.delete(f"author-{author.id}-publications")
        logging.getLogger(__name__).info(
            f"Created {len(authorships_to_create)} authorship "
            f"relationships for user {user.id}"
        )


def _normalize_doi(doi: str) -> str:
    """
    Normalize a DOI for consistent matching.

    Behavior:
    - Removes the `https://doi.org/` prefix if present.
    - Trims surrounding whitespace.
    - Lowercases the value.
    """
    if not doi:
        return doi
    return doi.replace("https://doi.org/", "").strip().lower()
