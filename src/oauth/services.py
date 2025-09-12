import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from django.db import transaction

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tasks import download_pdf
from user.models import Author
from user.tasks import invalidate_author_profile_caches
from utils.doi import DOI
from utils.openalex import OpenAlex
from utils.orcid import get_user_orcid_credentials, get_user_publication_dois

logger = logging.getLogger(__name__)


@dataclass
class OrcidPublicationData:
    dois: List[str]
    metadata: Dict[str, Dict[str, str]]


def fetch_orcid_publications(user, token: str, orcid_id: str) -> OrcidPublicationData:
    try:
        publications = get_user_publication_dois(token, orcid_id) or []
        valid_publications = [
            (DOI.get_bare_doi(item["doi"]), item)
            for item in publications
            if item.get("doi") and DOI.get_bare_doi(item.get("doi"))
        ]
        if not valid_publications:
            return OrcidPublicationData([], {})

        dois, publication_items = zip(*valid_publications)
        metadata_by_doi = {
            doi: {"title": item.get("title"), "abstract": item.get("abstract")}
            for doi, item in valid_publications
        }
        return OrcidPublicationData(list(dois), metadata_by_doi)

    except Exception:
        logger.exception("Failed to fetch ORCID publications for user %s", user.id)
        return OrcidPublicationData([], {})


def enrich_papers_with_openalex(dois: List[str]) -> None:
    if not dois:
        return

    openalex_client = OpenAlex()
    doi_batches = [dois[i : i + 200] for i in range(0, len(dois), 200)]
    all_works = []
    try:
        for batch_dois in doi_batches:
            response = openalex_client._get(
                "works",
                filters={
                    "filter": f"doi:{'|'.join(batch_dois)}",
                    "per-page": len(batch_dois),
                },
            )
            all_works.extend(response.get("results", []))
    except Exception:
        logger.warning("Batch fetch failed, using individual requests")
        all_works = list(
            filter(None, [get_single_work(openalex_client, doi) for doi in dois])
        )

    if all_works:
        process_openalex_works(all_works)


def get_single_work(openalex_client: OpenAlex, doi: str) -> Optional[dict]:
    try:
        return openalex_client.get_data_from_doi(doi)
    except Exception:
        return None


def update_papers_with_orcid_metadata(publication_data: OrcidPublicationData) -> None:
    if not publication_data.dois:
        return

    papers = Paper.objects.filter(doi__in=publication_data.dois).only(
        "id", "doi", "title", "abstract", "completeness", "file", "pdf_url", "url"
    )

    papers_needing_update = []
    papers_needing_pdf = []
    for paper in papers:
        orcid_metadata = publication_data.metadata.get(paper.doi, {})
        paper_was_updated = False
        if not paper.title and orcid_metadata.get("title"):
            paper.title = orcid_metadata["title"]
            paper_was_updated = True
        if not paper.abstract and orcid_metadata.get("abstract"):
            paper.abstract = orcid_metadata["abstract"]
            paper_was_updated = True
        if paper_was_updated:
            paper.set_paper_completeness()
            papers_needing_update.append(paper)
        if not paper.file and (paper.pdf_url or paper.url):
            papers_needing_pdf.append(paper.id)
    if papers_needing_update:
        Paper.objects.bulk_update(
            papers_needing_update, ["title", "abstract", "completeness"], batch_size=500
        )
    for paper_id in papers_needing_pdf:
        download_pdf.delay(paper_id)


def get_or_create_author_for_user(user) -> Author:
    author, _ = Author.objects.get_or_create(
        user=user,
        defaults={
            "first_name": user.first_name or "Unknown",
            "last_name": user.last_name or "User",
        },
    )
    return author


def get_existing_authorship_paper_ids(author: Author, dois: List[str]) -> set:
    return set(
        Authorship.objects.filter(author=author, paper__doi__in=dois).values_list(
            "paper_id", flat=True
        )
    )


def create_user_authorships(user, dois: List[str]) -> None:
    if not dois:
        return

    user_author = get_or_create_author_for_user(user)
    papers_by_doi = Paper.objects.filter(doi__in=dois).in_bulk(field_name="doi")
    existing_authorship_paper_ids = get_existing_authorship_paper_ids(user_author, dois)
    user_full_name = f"{user_author.first_name} {user_author.last_name}".strip()
    new_authorships = [
        Authorship(
            author=user_author,
            paper=paper,
            author_position="middle",
            is_corresponding=False,
            raw_author_name=user_full_name,
        )
        for doi, paper in papers_by_doi.items()
        if paper.id not in existing_authorship_paper_ids
    ]
    if new_authorships:
        Authorship.objects.bulk_create(new_authorships, ignore_conflicts=True)


def invalidate_user_caches(user) -> None:
    try:
        if hasattr(user, "author_profile") and user.author_profile:
            invalidate_author_profile_caches(None, user.author_profile.id)
    except Exception:
        logger.exception("Failed to invalidate caches for user %s", user.id)


@transaction.atomic
def sync_user_publications_from_orcid(user) -> None:
    account, token = get_user_orcid_credentials(user, auto_refresh=True)
    if not all([account, token, token.token]):
        return

    publication_data = fetch_orcid_publications(user, token.token, account.uid)
    if not publication_data.dois:
        return

    enrich_papers_with_openalex(publication_data.dois)
    update_papers_with_orcid_metadata(publication_data)
    create_user_authorships(user, publication_data.dois)
    invalidate_user_caches(user)
