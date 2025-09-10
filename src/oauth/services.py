import logging
import math
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

    scope = (account.extra_data or {}).get("scope")
    if scope and "/read-limited" not in scope and "/authenticate" not in scope:
        logger.warning(f"Token may not have required scope: {scope}")

    try:
        orcid_items = get_user_publication_dois(token.token, account.uid)
        if not orcid_items:
            return

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

    works = []
    if dois:
        open_alex = OpenAlex()
        try:
            max_batch_size = 200

            for i in range(0, len(dois), max_batch_size):
                doi_batch = dois[i : i + max_batch_size]
                doi_filter = "|".join(doi_batch)

                batch_response = open_alex._get(
                    "works",
                    filters={"filter": f"doi:{doi_filter}", "per-page": len(doi_batch)},
                )
                batch_works = batch_response.get("results", [])
                works.extend(batch_works)

            api_calls_used = math.ceil(len(dois) / max_batch_size)
            logger.info(
                f"Bulk fetched {len(works)} OpenAlex works from {len(dois)} DOIs "
                f"for user {user.id} using {api_calls_used} API calls"
            )
        except Exception as e:
            logger.warning(f"Bulk OpenAlex fetch failed, using optimized fallback: {e}")
            fallback_batch_size = 25

            for i in range(0, len(dois), fallback_batch_size):
                doi_batch = dois[i : i + fallback_batch_size]
                try:
                    doi_filter = "|".join(doi_batch)
                    batch_response = open_alex._get(
                        "works",
                        filters={
                            "filter": f"doi:{doi_filter}",
                            "per-page": len(doi_batch),
                        },
                    )
                    works.extend(batch_response.get("results", []))
                except Exception:
                    for doi in doi_batch:
                        try:
                            work = open_alex.get_data_from_doi(doi)
                            works.append(work)
                        except Exception:
                            continue

    if works:
        logger.info(
            f"Processing {len(works)} OpenAlex works in bulk for user {user.id}"
        )
        process_openalex_works(works)
    else:
        logger.info(f"No OpenAlex works found for user {user.id} DOIs")

    if not dois:
        return
    papers_qs = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    ).only("id", "doi", "title", "abstract", "completeness", "file", "pdf_url", "url")

    papers_by_doi = {paper.doi.lower(): paper for paper in papers_qs}
    papers_to_bulk_update = []
    pdf_download_tasks = []

    for doi in dois:
        if not (paper := papers_by_doi.get(doi.lower())):
            continue

        overlay = by_doi.get(doi, {})
        has_updates = False

        if not paper.title and overlay.get("title"):
            paper.title = overlay["title"]
            has_updates = True
        if not paper.abstract and overlay.get("abstract"):
            paper.abstract = overlay["abstract"]
            has_updates = True

        if has_updates:
            paper.set_paper_completeness()
            papers_to_bulk_update.append(paper)

        if not paper.file and (paper.pdf_url or paper.url):
            pdf_download_tasks.append(paper.id)

    if papers_to_bulk_update:
        Paper.objects.bulk_update(
            papers_to_bulk_update, ["title", "abstract", "completeness"], batch_size=500
        )
        logger.info(
            f"Bulk updated {len(papers_to_bulk_update)} papers for user {user.id}"
        )

    if pdf_download_tasks:
        for paper_id in pdf_download_tasks:
            download_pdf.delay(paper_id)
        logger.info(
            f"Queued {len(pdf_download_tasks)} PDF downloads for user {user.id}"
        )

    create_author_paper_relationships(user, dois)

    papers_updated = (
        len(papers_to_bulk_update) if "papers_to_bulk_update" in locals() else 0
    )
    logger.info(
        f"Completed ORCID sync for user {user.id}: "
        f"processed {len(dois)} DOIs, found {len(works)} OpenAlex works, "
        f"updated {papers_updated} papers"
    )


def create_author_paper_relationships(user, dois: List[str]) -> None:
    try:
        author = Author.objects.get(user=user)
    except Author.DoesNotExist:
        logging.getLogger(__name__).warning(
            f"No Author profile found for user {user.id}"
        )
        return

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
