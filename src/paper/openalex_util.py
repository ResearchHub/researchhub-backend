import copy
import logging
from typing import Any, Dict, List

from django.core.exceptions import ValidationError
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


def process_openalex_works(works):
    open_alex = OpenAlex()

    create_missing_authors(works)

    paper_to_openalex_data = create_and_update_papers(open_alex, works)

    # Fetch all authors at once
    paper_authors_by_work_id = fetch_authors_for_works(works)

    # Upsert concepts and associate to papers
    create_all_paper_tags(paper_to_openalex_data)

    # Process authorships with fetched author data
    for paper_id, paper_data in paper_to_openalex_data.items():
        work = paper_data["openalex_work"]
        openalex_authorships = work.get("authorships")
        if openalex_authorships and paper_id:
            try:
                relevant_oa_authors = paper_authors_by_work_id.get(work["id"], [])
                process_openalex_authorships(
                    openalex_authorships, paper_id, relevant_oa_authors
                )
            except Exception as e:
                sentry.log_error(
                    e, message=f"Failed to process authorships for paper_id: {paper_id}"
                )
        else:
            sentry.log_error(
                None,
                message=f"Authorships data is missing or paper_id is None for work: {work.get('id')}",
            )


def create_all_paper_tags(papers_to_openalex_data):
    from paper.paper_upload_tasks import create_paper_related_tags

    for paper_id, paper_data in papers_to_openalex_data.items():
        create_paper_related_tags(
            paper_data["paper"],
            paper_data["openalex_concepts"],
            paper_data["openalex_topics"],
        )


def create_and_update_papers(open_alex, works):
    from paper.models import Paper

    dois = [work.get("doi") for work in works]
    dois = [doi for doi in dois if doi is not None]
    # if dois have https://doi.org/ prefix, remove them
    dois = [doi.replace("https://doi.org/", "") for doi in dois]
    openalex_ids = [work.get("id") for work in works]

    # batch fetch existing papers
    existing_papers_query = (
        Paper.objects.filter(Q(doi__in=dois) | Q(openalex_id__in=openalex_ids))
        .only("doi", "id")
        .distinct()
    )
    existing_paper_map = {paper.doi: paper for paper in existing_papers_query}

    # Split works into two buckets: create and update
    papers_to_create = []
    papers_to_update = []

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
            papers_to_update.append((existing_paper, work))
        else:
            papers_to_create.append(work)

    paper_to_openalex_data = create_papers(open_alex, papers_to_create)
    # Add updated papers to the dictionary
    paper_to_openalex_data.update(update_papers(open_alex, papers_to_update))

    return paper_to_openalex_data


def create_papers(open_alex, works):
    from paper.models import Paper

    paper_to_openalex_data = {}

    for work in works:
        _work = copy.deepcopy(work)
        (
            openalex_paper,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(_work)

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


def update_papers(open_alex, works):
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


def fetch_authors_for_works(openalex_works) -> Dict[str, List[Dict[str, Any]]]:
    open_alex = OpenAlex()
    paper_authors = {}
    all_authors_to_fetch = set()
    batch_size = 100

    for work in openalex_works:
        oa_authorships = work.get("authorships", [])
        for oa_authorship in oa_authorships:
            author_openalex_id = oa_authorship.get("author", {}).get("id")
            just_id = author_openalex_id.split("/")[-1]
            all_authors_to_fetch.add(just_id)

    fetched_authors = {}
    for i in range(0, len(all_authors_to_fetch), batch_size):
        batch = list(all_authors_to_fetch)[i : i + batch_size]
        oa_authors_batch, _ = open_alex.get_authors(openalex_ids=batch)
        for author in oa_authors_batch:
            fetched_authors[author["id"]] = author

    for work in openalex_works:
        oa_authorships = work.get("authorships", [])
        oa_authors = []
        for oa_authorship in oa_authorships:
            oa_author_id = oa_authorship.get("author", {}).get("id")
            if oa_author_id in fetched_authors:
                oa_authors.append(fetched_authors[oa_author_id])
            else:
                logging.warning(
                    f"Author with OpenAlex ID not found: {oa_author_id}",
                )
                sentry.log_error(
                    None,
                    message=f"Author with OpenAlex ID not found: {oa_author_id}",
                )

        paper_authors[work.get("id")] = oa_authors

    return paper_authors


def create_missing_authors(openalex_works):
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
    existing_author_ids = set()
    for author in existing_authors:
        existing_author_ids.update(author.openalex_ids)

    openalex_authors_without_authors = [
        authorship.get("author", {})
        for authorship in openalex_authorships
        if authorship.get("author", {}).get("id") not in existing_author_ids
    ]

    authors_to_create = []
    for oa_author in openalex_authors_without_authors:
        author_name_parts = oa_author.get("display_name", "").split()

        authors_to_create.append(
            Author(
                first_name=author_name_parts[0],
                last_name=author_name_parts[-1],
                openalex_ids=[oa_author.get("id")],
                created_source=Author.SOURCE_OPENALEX,
            )
        )

    # Bulk create authors
    created_authors = Author.objects.bulk_create(authors_to_create)

    # Create wallets for new authors
    wallets_to_create = [Wallet(author=author) for author in created_authors]
    Wallet.objects.bulk_create(wallets_to_create)

    # Update existing_authors with newly created authors
    existing_authors = Author.objects.filter(
        openalex_ids__overlap=all_openalex_author_ids
    )


def process_openalex_authorships(openalex_authorships, related_paper_id, oa_authors):
    """
    Iterates through authorships associated with an OpenAlex work and create related objects such as
    AuthorInstitution, Authorship, and Author objects. Related models will be updated if they already exist.
    https://docs.openalex.org/api-entities/works/work-object/authorship-object
    """
    from institution.models import Institution
    from paper.models import Paper
    from paper.related_models.authorship_model import Authorship
    from user.related_models.author_model import Author

    related_paper = Paper.objects.get(id=related_paper_id)
    print(f"Processing authorships for paper: {related_paper.title}")
    authors_in_this_work = []
    all_openalex_ids = [
        oa_authorship.get("author", {}).get("id")
        for oa_authorship in openalex_authorships
    ]
    authors = Author.objects.filter(openalex_ids__overlap=all_openalex_ids)

    authorships_to_create_or_update = []
    authorship_institution_relations = {}

    authors_dict = {}
    for author in authors:
        for openalex_id in author.openalex_ids:
            if openalex_id not in authors_dict:
                authors_dict[openalex_id] = []

            authors_dict[openalex_id].append(author)

    for oa_authorship in openalex_authorships:
        author_position = oa_authorship.get("author_position")
        author_openalex_id = oa_authorship.get("author", {}).get("id")

        authors = authors_dict.get(author_openalex_id, [])

        for author in authors:
            # Associate paper with author
            related_paper.authors.add(author)

            is_corresponding = oa_authorship.get("is_corresponding")
            raw_author_name = oa_authorship.get("author", {}).get("display_name")

            authorship = Authorship(
                author=author,
                paper=related_paper,
                author_position=author_position,
                is_corresponding=is_corresponding,
                raw_author_name=raw_author_name,
            )
            authorships_to_create_or_update.append(authorship)

            authors_in_this_work.append(author)

            # Set institutions associated with authorships if they do not already exist
            for oa_inst in oa_authorship.get("institutions", []):
                institution = Institution.upsert_from_openalex(oa_inst)
                if institution:
                    key = f"{authorship.author_id}:{authorship.paper_id}"
                    if key not in authorship_institution_relations:
                        authorship_institution_relations[key] = []
                    authorship_institution_relations[key].append(institution)

    Authorship.objects.bulk_create(
        authorships_to_create_or_update,
        update_conflicts=True,
        unique_fields=["author", "paper"],
        update_fields=["author_position", "is_corresponding", "raw_author_name"],
    )

    # Fetch the relevant authorships with specific author/paper combinations
    author_paper_pairs = [(a.author, a.paper) for a in authorships_to_create_or_update]
    authorships = Authorship.objects.filter(
        Q(author__in=[author for author, _ in author_paper_pairs])
        & Q(paper__in=[paper for _, paper in author_paper_pairs])
    )

    for authorship in authorships:
        for institution in authorship_institution_relations.get(
            f"{authorship.author_id}:{authorship.paper_id}", []
        ):
            authorship.institutions.add(institution)

    # Update authors with additional metadata from OpenAlex
    all_openalex_ids = [author.get("id") for author in oa_authors]
    authors = Author.objects.filter(openalex_ids__overlap=all_openalex_ids)

    authors_dict = {}
    for author in authors:
        for openalex_id in author.openalex_ids:
            if openalex_id not in authors_dict:
                authors_dict[openalex_id] = []

            authors_dict[openalex_id].append(author)

    for oa_author in oa_authors:
        try:
            authors = authors_dict.get(oa_author.get("id"), [])
            for author in authors:
                merge_openalex_author_with_researchhub_author(oa_author, author)

        except Exception as e:
            logging.warning(
                f"Author with OpenAlex ID failed to be merged: {oa_author.get('id')}",
            )
            sentry.log_error(
                e,
                message=f"Author with OpenAlex ID failed to be merged {oa_author.get('id')}",
            )
            continue

    # Create co-author relationships
    coauthor_objects = []
    for i, author in enumerate(authors_in_this_work):
        coauthor_count = 0
        for coauthor in authors_in_this_work:
            if author != coauthor:
                coauthor_objects.append(
                    CoAuthor(
                        author=author, coauthor=coauthor, paper_id=related_paper_id
                    )
                )
                coauthor_count += 1

            if coauthor_count >= 10:
                break

    CoAuthor.objects.bulk_create(coauthor_objects, ignore_conflicts=True)


def merge_openalex_author_with_researchhub_author(openalex_author, researchhub_author):
    """
    Merges the OpenAlex author data with the ResearchHub author data. This is necessary because the OpenAlex author data
    """
    with transaction.atomic():
        # Update basic metadata fields
        researchhub_author.i10_index = openalex_author.get("summary_stats", {}).get(
            "i10_index"
        )
        researchhub_author.h_index = openalex_author.get("summary_stats", {}).get(
            "h_index"
        )
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
        AuthorInstitution.objects.bulk_create(
            author_institutions, ignore_conflicts=True
        )

    return researchhub_author
