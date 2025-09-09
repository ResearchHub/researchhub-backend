import logging
from typing import List

from django.core.cache import cache

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tasks import download_pdf
from user.models import Author
from utils.openalex import OpenAlex
from utils.orcid import get_orcid_account_and_token, list_user_dois


def sync_orcid_for_user(user) -> None:
    """
    Pull ORCID works for the given user and merge into our Paper records.

    Steps:
    1) Read DOIs (plus optional title/abstract) from ORCID.
    2) Query OpenAlex for each DOI to get canonical work records.
    3) Pass works through our OpenAlex ingestion pipeline.
    4) Overlay missing title/abstract from ORCID values when OpenAlex lacks them,
       recompute completeness, and enqueue a PDF download if needed.
    """
    account, token = get_orcid_account_and_token(user, auto_refresh=True)
    if not (account and token and token.token):
        return

    orcid_id = account.uid
    logger = logging.getLogger(__name__)

    logger.info(f"Starting ORCID sync for user {user.id}")

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

    # 1) Pull DOIs from ORCID
    try:
        orcid_items = list_user_dois(token.token, orcid_id)
        by_doi = {}
        dois = []
        for item in orcid_items:
            doi = _normalize_doi(item.get("doi"))
            if doi:
                dois.append(doi)
                by_doi[doi] = {
                    "title": item.get("title"),
                    "abstract": item.get("abstract"),
                }

        if not dois:
            return
    except Exception as e:
        logger.error(f"Failed to fetch ORCID works for user {user.id}: {e}")
        return

    # 2) Fetch OpenAlex works and process them
    works = []
    for doi in dois:
        try:
            works.append(OpenAlex().get_data_from_doi(doi))
        except Exception:
            pass  # Ignore DOIs OpenAlex can't resolve

    if works:
        process_openalex_works(works)

    # 3) Overlay missing data and create authorships
    for doi in dois:
        paper = Paper.objects.filter(doi__iexact=doi).first()
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
            paper.save(update_fields=dirty_fields)

        # Trigger PDF download if needed
        if not paper.file and (paper.pdf_url or paper.url):
            download_pdf.delay(paper.id)

    # Create authorship relationships
    _create_orcid_authorships(user, dois)

    logger.info(f"Successfully completed ORCID sync for user {user.id}")


def _create_orcid_authorships(user, dois: List[str]) -> None:
    """Create authorship relationships between the ORCID user and imported papers."""
    try:
        author = Author.objects.get(user=user)
    except Author.DoesNotExist:
        logging.getLogger(__name__).warning(
            f"No Author profile found for user {user.id}"
        )
        return

    created_count = 0
    for doi in dois:
        paper = Paper.objects.filter(doi__iexact=doi).first()
        if paper and not Authorship.objects.filter(author=author, paper=paper).exists():
            Authorship.objects.create(
                author=author,
                paper=paper,
                author_position="middle",
                is_corresponding=False,
                raw_author_name=f"{author.first_name} {author.last_name}".strip(),
            )
            created_count += 1

    if created_count > 0:
        cache.delete(f"author-{author.id}-publications")
        logging.getLogger(__name__).info(
            f"Created {created_count} authorship relationships for user {user.id}"
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
