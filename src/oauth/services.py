import logging
import re
from typing import List

from django.db import transaction

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tasks import download_pdf
from user.models import Author
from utils.doi import DOI
from utils.openalex import OpenAlex
from utils.orcid import get_user_orcid_credentials, get_user_publication_dois


@transaction.atomic
def sync_user_publications_from_orcid(user) -> None:
    account, token = get_user_orcid_credentials(user, auto_refresh=True)
    if not (account and token and token.token):
        return

    logger = logging.getLogger(__name__)
    logger.info(f"Starting ORCID sync for user {user.id}")

    # Check scope
    scope = (account.extra_data or {}).get("scope")
    if scope and "/read-limited" not in scope and "/authenticate" not in scope:
        logger.warning(f"Token may not have required scope: {scope}")

    try:
        orcid_items = get_user_publication_dois(token.token, account.uid)
        if not orcid_items:
            return

        # Filter and normalize DOIs
        valid_items = [
            (item, DOI.get_bare_doi(item["doi"]))
            for item in orcid_items
            if item.get("doi") and DOI.get_bare_doi(item["doi"])
        ]

        if not valid_items:
            return

        dois = [doi for _, doi in valid_items]
        by_doi = {
            doi: {"title": item.get("title"), "abstract": item.get("abstract")}
            for item, doi in valid_items
        }
    except Exception as e:
        logger.error(f"Failed to fetch ORCID works for user {user.id}: {e}")
        return

    # Fetch OpenAlex works in bulk
    works = []
    if dois:
        open_alex = OpenAlex()
        try:
            # Process in batches of 50 (OpenAlex limit)
            for i in range(0, len(dois), 50):
                batch_works, _ = open_alex.get_works(
                    filters={"filter": f"doi:{'|'.join(dois[i:i+50])}"}
                )
                works.extend(batch_works)
        except Exception as e:
            logger.warning(f"Bulk OpenAlex fetch failed, falling back: {e}")
            # Fallback to individual requests
            for doi in dois:
                try:
                    works.append(open_alex.get_data_from_doi(doi))
                except Exception:
                    continue

    if works:
        process_openalex_works(works)

    papers_qs = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    ).only("id", "doi", "title", "abstract", "completeness", "file", "pdf_url", "url")

    papers_by_doi = {paper.doi.lower(): paper for paper in papers_qs}

    papers_to_update, pdf_download_ids = [], []

    for doi in dois:
        if not (paper := papers_by_doi.get(doi.lower())):
            continue

        overlay = by_doi.get(doi, {})
        dirty_fields = []

        # Update missing fields
        if not paper.title and overlay.get("title"):
            paper.title = overlay["title"]
            dirty_fields.append("title")
        if not paper.abstract and overlay.get("abstract"):
            paper.abstract = overlay["abstract"]
            dirty_fields.append("abstract")

        if dirty_fields:
            paper.set_paper_completeness()
            papers_to_update.append((paper, dirty_fields + ["completeness"]))

        if not paper.file and (paper.pdf_url or paper.url):
            pdf_download_ids.append(paper.id)

    # Bulk operations
    for paper, fields in papers_to_update:
        paper.save(update_fields=fields)
    for paper_id in pdf_download_ids:
        download_pdf.delay(paper_id)

    create_author_paper_relationships(user, dois)
    logger.info(f"Completed ORCID sync for user {user.id}")


def create_author_paper_relationships(user, dois: List[str]) -> None:
    try:
        author = Author.objects.get(user=user)
    except Author.DoesNotExist:
        logging.getLogger(__name__).warning(
            f"No Author profile found for user {user.id}"
        )
        return

    # Get papers and existing authorships
    doi_regex = r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    papers_by_doi = {
        p.doi.lower(): p
        for p in Paper.objects.filter(doi__iregex=doi_regex).only("id", "doi")
    }
    existing_paper_ids = set(
        Authorship.objects.filter(
            author=author, paper__doi__iregex=doi_regex
        ).values_list("paper_id", flat=True)
    )

    # Create missing authorships
    authorships_to_create = [
        Authorship(
            author=author,
            paper=papers_by_doi[doi.lower()],
            author_position="middle",
            is_corresponding=False,
            raw_author_name=f"{author.first_name} {author.last_name}".strip(),
        )
        for doi in dois
        if doi.lower() in papers_by_doi
        and papers_by_doi[doi.lower()].id not in existing_paper_ids
    ]

    if authorships_to_create:
        Authorship.objects.bulk_create(authorships_to_create, ignore_conflicts=True)
        logging.getLogger(__name__).info(
            f"Created {len(authorships_to_create)} authorships for user {user.id}"
        )
