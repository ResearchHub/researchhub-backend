import logging
import re
from typing import List

from django.db import transaction

from paper.models import Paper
from paper.openalex_util import process_openalex_works
from paper.related_models.authorship_model import Authorship
from paper.tasks import download_pdf
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PAPER as PAPER_DOC_TYPE,
)
from user.models import Author
from user.tasks import invalidate_author_profile_caches
from utils.doi import DOI
from utils.openalex import OpenAlex
from utils.orcid import get_user_orcid_credentials, get_user_publication_dois


@transaction.atomic
def sync_user_publications_from_orcid(user) -> None:
    account, token = get_user_orcid_credentials(user, auto_refresh=True)
    if not (account and token and token.token):
        return

    try:
        orcid_items = get_user_publication_dois(token.token, account.uid)
        valid_items = [
            (item, DOI.get_bare_doi(item["doi"]))
            for item in orcid_items or []
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
        logging.getLogger(__name__).error(
            f"Failed to fetch ORCID works for user {user.id}: {e}"
        )
        return

    works = []
    if dois:
        open_alex = OpenAlex()
        try:
            for i in range(0, len(dois), 200):
                batch_response = open_alex._get(
                    "works",
                    filters={
                        "filter": f"doi:{'|'.join(dois[i:i + 200])}",
                        "per-page": min(200, len(dois) - i),
                    },
                )
                works.extend(batch_response.get("results", []))
        except Exception:
            for doi in dois:
                try:
                    works.append(open_alex.get_data_from_doi(doi))
                except Exception:
                    continue

    if works:
        process_openalex_works(works)

    if not dois:
        return

    _ensure_papers_have_unified_documents(dois)
    papers_qs = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$"
    ).only("id", "doi", "title", "abstract", "completeness", "file", "pdf_url", "url")
    papers_by_doi = {paper.doi.lower(): paper for paper in papers_qs}
    papers_to_update, pdf_tasks = [], []

    for doi in dois:
        if paper := papers_by_doi.get(doi.lower()):
            overlay = by_doi.get(doi, {})
            updated = False
            if not paper.title and overlay.get("title"):
                paper.title, updated = overlay["title"], True
            if not paper.abstract and overlay.get("abstract"):
                paper.abstract, updated = overlay["abstract"], True
            if updated:
                paper.set_paper_completeness()
                papers_to_update.append(paper)
            if not paper.file and (paper.pdf_url or paper.url):
                pdf_tasks.append(paper.id)

    if papers_to_update:
        Paper.objects.bulk_update(
            papers_to_update, ["title", "abstract", "completeness"], batch_size=500
        )
        for paper_id in pdf_tasks:
            download_pdf.delay(paper_id)

    create_author_paper_relationships(user, dois)
    _invalidate_author_caches(user)


def create_author_paper_relationships(user, dois: List[str]) -> None:
    author, _ = Author.objects.get_or_create(
        user=user,
        defaults={
            "first_name": user.first_name or "Unknown",
            "last_name": user.last_name or "User",
        },
    )
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

    authorships = [
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
    if authorships:
        Authorship.objects.bulk_create(authorships, ignore_conflicts=True)


def _ensure_papers_have_unified_documents(dois: List[str]) -> None:
    if not dois:
        return
    papers = Paper.objects.filter(
        doi__iregex=r"^(" + "|".join(re.escape(doi) for doi in dois) + ")$",
        unified_document__isnull=True,
    )
    if papers:
        unified_docs = [
            ResearchhubUnifiedDocument(document_type=PAPER_DOC_TYPE, score=paper.score)
            for paper in papers
        ]
        ResearchhubUnifiedDocument.objects.bulk_create(unified_docs)
        for i, paper in enumerate(papers):
            paper.unified_document = unified_docs[i]
        Paper.objects.bulk_update(papers, ["unified_document"], batch_size=500)


def _invalidate_author_caches(user) -> None:
    try:
        if hasattr(user, "author_profile") and user.author_profile:
            invalidate_author_profile_caches(None, user.author_profile.id)
    except Exception:
        pass
