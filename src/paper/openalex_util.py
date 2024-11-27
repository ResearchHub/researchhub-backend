import copy
import logging
import urllib.parse
from typing import Any, Dict, List

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError, transaction
from django.db.models import Q
from simple_history.utils import bulk_update_with_history

import utils.sentry as sentry
from institution.models import Institution
from paper.related_models.citation_model import Citation, Source
from user.related_models.author_contribution_summary_model import (
    AuthorContributionSummary,
)
from user.related_models.author_institution import AuthorInstitution
from user.related_models.coauthor_model import CoAuthor
from utils.openalex import OpenAlex

# Only these particular fields will be updated when an OpenAlex
# paper which matches an existing paper is found
PAPER_FIELDS_ALLOWED_TO_UPDATE = [
    "paper_publish_date",
    "alternate_ids",
    "citations",
    "abstract",
    "pdf_license",
    "pdf_license_url",
    "oa_status",
    "is_open_access",
    "open_alex_raw_json",
    "external_source",
    "work_type",
    "openalex_id",
    "is_retracted",
    "mag_id",
    "pubmed_id",
    "pubmed_central_id",
    "work_type",
    "language",
    "title",
    "paper_title",
    "doi",
    "url",
    "abstract",
    "retrieved_from_external_source",
]

"""
This dictionary maps OpenAlex sources (`external_source`) to ResearchHub journal hubs. 
It is used to automatically tag papers with the appropriate journal hub when they are fetched from OpenAlex.
Note: If the name of the journal hub changes, this dictionary will need to be updated.
"""
OPENALEX_SOURCES_TO_JOURNAL_HUBS: Dict[str, str] = {
    "arXiv (Cornell University)": "Arxiv",
    "bioRxiv (Cold Spring Harbor Laboratory)": "Biorxiv",
    "medRxiv (Cold Spring Harbor Laboratory)": "Medrxiv",
    "ChemRxiv": "Chemrxiv",
    "Research Square (Research Square)": "Research Square",
    "OSF Preprints (OSF Preprints)": "Osf Preprints",
    "PeerJ": "Peerj",
    "Authorea (Authorea)": "Authorea",
    "SSRN Electronic Journal": "Ssrn",
}


def process_openalex_works(works):
    open_alex = OpenAlex()

    authors = create_authors(works)
    authors_by_oa_id = build_authors_by_oa_id_dict(authors)

    paper_to_openalex_data = create_and_update_papers(open_alex, works)

    # Fetch all authors at once from openalex
    fetched_oa_authors = fetch_authors_for_works(works)
    oa_authors_by_work_id = build_oa_authors_by_work_id_dict(works, fetched_oa_authors)

    merge_openalex_authors_with_researchhub_authors(
        fetched_oa_authors, authors_by_oa_id
    )

    create_all_paper_tags(paper_to_openalex_data)

    create_openalex_authorships_and_institutions(
        paper_to_openalex_data, oa_authors_by_work_id, authors_by_oa_id
    )

    create_coauthors(paper_to_openalex_data, oa_authors_by_work_id, authors_by_oa_id)


def create_all_paper_tags(papers_to_openalex_data):
    from paper.paper_upload_tasks import create_paper_related_tags

    for paper_id, paper_data in papers_to_openalex_data.items():
        create_paper_related_tags(
            paper_data["paper"],
            paper_data["openalex_concepts"],
            paper_data["openalex_topics"],
        )


def create_and_update_papers(open_alex, works) -> Dict[int, Dict[str, Any]]:
    from paper.models import Paper

    dois = [work.get("doi") for work in works]
    dois = [doi for doi in dois if doi is not None]
    # if dois have https://doi.org/ prefix, remove them
    dois = [doi.replace("https://doi.org/", "") for doi in dois]
    openalex_ids = [work.get("id") for work in works]

    # batch fetch existing papers
    doi_q_objects = Q()
    for doi in dois:
        doi_q_objects |= Q(doi__iexact=doi)

    existing_papers_query = (
        Paper.objects.filter(doi_q_objects | Q(openalex_id__in=openalex_ids))
        .only("doi", "id", "unified_document")
        .distinct()
    )
    existing_paper_map = {paper.doi: paper for paper in existing_papers_query}

    # Split works into two buckets: create and update
    papers_to_create = {}
    papers_to_update = {}

    for work in works:
        # When fetched in batch, OpneAlex will truncate authors beyond 100.
        # If this is the case, we need to fetch the full work
        # https://docs.openalex.org/api-entities/authors/limitations
        if work.get("is_authors_truncated", False):
            just_id = work.get("id").split("/")[-1]
            work = open_alex.get_work(just_id)

        doi = work.get("doi")
        if doi is None:
            print(f"No Doi for result: {work.get('id')}")
            continue

        existing_paper = existing_paper_map.get(doi)
        if existing_paper is None:
            doi = doi.replace("https://doi.org/", "")
            existing_paper = existing_paper_map.get(doi)

        if existing_paper is not None:
            papers_to_update[doi] = (existing_paper, work)
        else:
            papers_to_create[doi] = work

    paper_to_openalex_data = create_papers(open_alex, papers_to_create.values())
    # Add updated papers to the dictionary
    paper_to_openalex_data.update(update_papers(open_alex, papers_to_update.values()))

    return paper_to_openalex_data


def create_papers(open_alex, works) -> Dict[int, Dict[str, Any]]:
    from paper.models import Paper

    paper_to_openalex_data = {}

    for work in works:
        _work = copy.deepcopy(work)
        (
            openalex_paper,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(_work)

        # Clean the pdf_url
        if openalex_paper.get("pdf_url"):
            openalex_paper["pdf_url"] = clean_url(openalex_paper["pdf_url"])

        paper = Paper(**openalex_paper)

        # Validate paper
        try:
            paper.clean_fields()
            paper.clean()
        except ValidationError as e:
            sentry.log_error(
                e,
                message=f"Failed to validate paper: {paper.doi}, {work.get('id')}",
            )
            continue

        try:
            with transaction.atomic():
                paper.save()

            Citation(
                paper=paper,
                total_citation_count=paper.citations,
                citation_change=paper.citations,
                source=Source.OpenAlex.value,
            ).save()

            # Successfully saved paper, add to map
            paper_to_openalex_data[paper.id] = {
                "openalex_concepts": openalex_concepts,
                "openalex_topics": openalex_topics,
                "openalex_work": work,
                "paper": paper,
            }
        except IntegrityError as e:
            sentry.log_error(
                e, message=f"Failed to save paper, DOI already exists: {paper.doi}"
            )
            continue
        except Exception as e:
            sentry.log_error(
                e, message=f"Failed to save paper, unexpected error: {paper.doi}"
            )
            continue

    return paper_to_openalex_data


def update_papers(open_alex, works) -> Dict[int, Dict[str, Any]]:
    from paper.models import Paper

    paper_to_openalex_data = {}

    for existing_paper, work in works:
        _work = copy.deepcopy(work)
        (
            openalex_paper,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(_work)

        # we didn't fetch all fields in the initial paper query (we used .only()),
        # so we need to explicitly fetch them if we want to update them.
        # otherwise django doesn't update them, e.g. paper_publish_date
        existing_paper.refresh_from_db(fields=[*PAPER_FIELDS_ALLOWED_TO_UPDATE])

        previous_citation_count = Citation.citation_count(existing_paper)

        if previous_citation_count != openalex_paper.get("citations"):
            Citation(
                paper=existing_paper,
                total_citation_count=openalex_paper.get("citations"),
                citation_change=openalex_paper.get("citations")
                - previous_citation_count,
                source=Source.OpenAlex.value,
            ).save()

        for field in PAPER_FIELDS_ALLOWED_TO_UPDATE:
            setattr(existing_paper, field, openalex_paper.get(field))

        paper_to_openalex_data[existing_paper.id] = {
            "openalex_concepts": openalex_concepts,
            "openalex_topics": openalex_topics,
            "openalex_work": work,
            "paper": existing_paper,
        }

    # perform batch update
    if works and len(works) > 0:
        fields_to_update = [*PAPER_FIELDS_ALLOWED_TO_UPDATE]
        papers_to_update = [paper for paper, _ in works]
        try:
            bulk_update_with_history(papers_to_update, Paper, fields_to_update)
        except Exception as e:
            sentry.log_error(e, message="Failed to bulk update papers")

    return paper_to_openalex_data


def fetch_authors_for_works(openalex_works) -> List[Dict[str, Any]]:
    open_alex = OpenAlex()
    all_authors_to_fetch = set()
    batch_size = 100

    for work in openalex_works:
        oa_authorships = work.get("authorships", [])
        for oa_authorship in oa_authorships:
            author_openalex_id = oa_authorship.get("author", {}).get("id")
            just_id = author_openalex_id.split("/")[-1]
            all_authors_to_fetch.add(just_id)

    fetched_oa_authors = []
    for i in range(0, len(all_authors_to_fetch), batch_size):
        batch = list(all_authors_to_fetch)[i : i + batch_size]
        oa_authors_batch, _ = open_alex.get_authors(openalex_ids=batch)
        fetched_oa_authors.extend(oa_authors_batch)
    return fetched_oa_authors


def build_oa_authors_by_work_id_dict(
    openalex_works, fetched_oa_authors
) -> Dict[str, List[Dict[str, Any]]]:
    fetched_oa_authors_by_id = {author["id"]: author for author in fetched_oa_authors}

    oa_authors_by_work_id = {}
    for work in openalex_works:
        oa_authorships = work.get("authorships", [])
        oa_authors = []
        for oa_authorship in oa_authorships:
            oa_author_id = oa_authorship.get("author", {}).get("id")
            if oa_author_id in fetched_oa_authors_by_id:
                oa_authors.append(fetched_oa_authors_by_id[oa_author_id])
            else:
                logging.warning(
                    f"Author with OpenAlex ID not found: {oa_author_id}",
                )
                sentry.log_error(
                    None,
                    message=f"Author with OpenAlex ID not found: {oa_author_id}",
                )

        oa_authors_by_work_id[work.get("id")] = oa_authors

    return oa_authors_by_work_id


def create_authors(openalex_works) -> List["Author"]:
    from purchase.models import Wallet
    from user.related_models.author_model import Author

    # Get all authorships from the works
    openalex_authorships = [work.get("authorships", []) for work in openalex_works]
    openalex_authorships = [
        item for sublist in openalex_authorships for item in sublist
    ]

    all_openalex_author_ids = [
        oa_authorship.get("author", {}).get("id")
        for oa_authorship in openalex_authorships
    ]

    existing_authors = Author.objects.filter(
        openalex_ids__overlap=all_openalex_author_ids
    )
    existing_oa_author_ids = set()
    for author in existing_authors:
        existing_oa_author_ids.update(author.openalex_ids)

    openalex_authors_without_authors = [
        authorship.get("author", {})
        for authorship in openalex_authorships
        if authorship.get("author", {}).get("id") not in existing_oa_author_ids
    ]

    authors_to_create = {}
    for oa_author in openalex_authors_without_authors:
        author_name_parts = oa_author.get("display_name", "").split()

        authors_to_create[oa_author.get("id")] = Author(
            first_name=author_name_parts[0],
            last_name=author_name_parts[-1],
            openalex_ids=[oa_author.get("id")],
            created_source=Author.SOURCE_OPENALEX,
        )

    # Bulk create authors
    created_authors = Author.objects.bulk_create(authors_to_create.values())

    # Create wallets for new authors
    wallets_to_create = [Wallet(author=author) for author in created_authors]
    Wallet.objects.bulk_create(wallets_to_create)

    return Author.objects.filter(openalex_ids__overlap=all_openalex_author_ids)


def build_authors_by_oa_id_dict(authors) -> Dict[str, List["Author"]]:
    authors_by_oa_id = {}
    for author in authors:
        for openalex_id in author.openalex_ids:
            if openalex_id not in authors_by_oa_id:
                authors_by_oa_id[openalex_id] = []

            authors_by_oa_id[openalex_id].append(author)

    return authors_by_oa_id


def create_openalex_authorships_and_institutions(
    paper_to_openalex_data, oa_authors_by_work_id, authors_by_oa_id
):
    from institution.models import Institution
    from paper.related_models.authorship_model import Authorship

    authorships_to_create_or_update = {}
    authorship_institution_relations = {}

    for paper_id, paper_data in paper_to_openalex_data.items():
        work = paper_data["openalex_work"]
        related_paper = paper_data["paper"]
        openalex_authorships = work.get("authorships")
        oa_authors = oa_authors_by_work_id.get(work["id"], [])

        if not openalex_authorships or not paper_id:
            sentry.log_error(
                None,
                message=f"Authorships data is missing or paper_id is None for work: {work.get('id')}",
            )
            continue

        print(f"Processing authorships for paper: {related_paper.title}")
        authors = []
        for oa_author in oa_authors:
            authors.extend(authors_by_oa_id.get(oa_author.get("id"), []))

        for oa_authorship in openalex_authorships:
            author_position = oa_authorship.get("author_position")
            author_openalex_id = oa_authorship.get("author", {}).get("id")

            authors_for_oa_author = authors_by_oa_id.get(author_openalex_id, [])

            for author in authors_for_oa_author:
                # Associate paper with author
                is_corresponding = oa_authorship.get("is_corresponding")
                raw_author_name = oa_authorship.get("author", {}).get("display_name")

                authorship = Authorship(
                    author=author,
                    paper=related_paper,
                    author_position=author_position,
                    is_corresponding=is_corresponding,
                    raw_author_name=raw_author_name,
                )
                key = f"{authorship.author_id}:{authorship.paper_id}"

                authorships_to_create_or_update[key] = authorship

                # Set institutions associated with authorships if they do not already exist
                for oa_inst in oa_authorship.get("institutions", []):
                    try:
                        institution = Institution.upsert_from_openalex(oa_inst)
                        if institution:
                            if key not in authorship_institution_relations:
                                authorship_institution_relations[key] = []
                            authorship_institution_relations[key].append(institution)
                    except Exception as e:
                        sentry.log_error(
                            e,
                            message=f"Failed to upsert institution: {e}",
                        )

    Authorship.objects.bulk_create(
        authorships_to_create_or_update.values(),
        update_conflicts=True,
        unique_fields=["author", "paper"],
        update_fields=["author_position", "is_corresponding", "raw_author_name"],
    )

    # Fetch the relevant authorships with specific author/paper combinations
    author_paper_pairs = [
        (a.author, a.paper) for a in authorships_to_create_or_update.values()
    ]
    authorships = Authorship.objects.filter(
        Q(author__in=[author for author, _ in author_paper_pairs])
        & Q(paper__in=[paper for _, paper in author_paper_pairs])
    )

    for authorship in authorships:
        for institution in authorship_institution_relations.get(
            f"{authorship.author_id}:{authorship.paper_id}", []
        ):
            authorship.institutions.add(institution)


def create_coauthors(paper_to_openalex_data, oa_authors_by_work_id, authors_by_oa_id):
    for _, paper_data in paper_to_openalex_data.items():
        work = paper_data["openalex_work"]
        related_paper = paper_data["paper"]
        oa_authors = oa_authors_by_work_id.get(work["id"], [])
        authors = []
        for oa_author in oa_authors:
            authors.extend(authors_by_oa_id.get(oa_author.get("id"), []))

        # Create co-author relationships
        coauthor_objects = []
        for author in authors:
            coauthor_count = 0
            for coauthor in authors:
                if author != coauthor:
                    coauthor_objects.append(
                        CoAuthor(
                            author=author, coauthor=coauthor, paper_id=related_paper.id
                        )
                    )
                    coauthor_count += 1

                if coauthor_count >= 10:
                    break

        CoAuthor.objects.bulk_create(coauthor_objects, ignore_conflicts=True)


def merge_openalex_authors_with_researchhub_authors(oa_authors, authors_by_oa_id):
    for oa_author in oa_authors:
        try:
            rh_authors = authors_by_oa_id.get(oa_author.get("id"), [])
            for rh_author in rh_authors:
                merge_openalex_author_with_researchhub_author(oa_author, rh_author)

        except Exception as e:
            logging.warning(
                f"Author with OpenAlex ID failed to be merged: {oa_author.get('id')}",
            )
            sentry.log_error(
                e,
                message=f"Author with OpenAlex ID failed to be merged {oa_author.get('id')}",
            )
            continue


def merge_openalex_author_with_researchhub_author(openalex_author, researchhub_author):
    """
    Merges the OpenAlex author data with the ResearchHub author data. This is necessary because the OpenAlex author data
    """
    # Update basic metadata fields
    researchhub_author.i10_index = openalex_author.get("summary_stats", {}).get(
        "i10_index"
    )
    researchhub_author.h_index = openalex_author.get("summary_stats", {}).get("h_index")
    researchhub_author.two_year_mean_citedness = openalex_author.get(
        "summary_stats", {}
    ).get("2yr_mean_citedness")
    researchhub_author.orcid_id = openalex_author.get("orcid")

    # Associate this openalex id with the author
    if openalex_author["id"] not in researchhub_author.openalex_ids:
        researchhub_author.openalex_ids.append(openalex_author["id"])

    researchhub_author.save()

    # Prepare data for bulk operations
    contribution_summaries = []
    author_institutions = []

    # Process activity by year
    activity_by_year = openalex_author.get("counts_by_year", [])
    for activity in activity_by_year:
        contribution_summaries.append(
            AuthorContributionSummary(
                source=AuthorContributionSummary.SOURCE_OPENALEX,
                author=researchhub_author,
                year=activity.get("year"),
                works_count=activity.get("works_count"),
                citation_count=activity.get("cited_by_count"),
            )
        )

    # Process affiliations
    affiliations = openalex_author.get("affiliations", [])
    institution_ids = [
        aff.get("institution", {}).get("id")
        for aff in affiliations
        if aff.get("institution")
    ]
    existing_institutions = {
        inst.openalex_id: inst
        for inst in Institution.objects.filter(openalex_id__in=institution_ids)
    }

    for affiliation in affiliations:
        oa_institution = affiliation.get("institution")
        if not oa_institution:
            continue

        institution = existing_institutions.get(oa_institution["id"])
        if not institution:
            continue

        author_institutions.append(
            AuthorInstitution(
                author=researchhub_author,
                institution=institution,
                years=affiliation.get("years", []),
            )
        )

    # Perform bulk operations
    AuthorContributionSummary.objects.bulk_create(
        contribution_summaries,
        update_conflicts=True,
        unique_fields=["source", "author", "year"],
        update_fields=["works_count", "citation_count"],
    )
    AuthorInstitution.objects.bulk_create(author_institutions, ignore_conflicts=True)

    return researchhub_author


def clean_url(url):
    url = url.strip()

    url = urllib.parse.quote(url, safe=":/?&=")

    validate = URLValidator()
    try:
        validate(url)
    except ValidationError:
        return None

    return url
