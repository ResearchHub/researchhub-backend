import copy
import logging

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
    from paper.models import Paper
    from paper.paper_upload_tasks import create_paper_related_tags

    open_alex = OpenAlex()

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
    create_papers = []
    update_papers = []

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
            update_papers.append((existing_paper, work))
        else:
            create_papers.append(work)

    paper_to_openalex_data = {}

    # Create new papers
    for work in create_papers:
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

    # Prepare papers for batch update
    for existing_paper, work in update_papers:
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
    if update_papers and len(update_papers) > 0:
        fields_to_update = [*PAPER_FIELDS_ALLOWED_TO_UPDATE]
        papers_to_update = [paper for paper, _ in update_papers]
        try:
            bulk_update_with_history(papers_to_update, Paper, fields_to_update)
        except Exception as e:
            sentry.log_error(e, message="Failed to bulk update papers")

    # Fetch all authors at once
    oa_authors = fetch_authors_for_works(works)

    # Upsert concepts and associate to papers
    for paper_id, paper_data in paper_to_openalex_data.items():
        work = paper_data["openalex_work"]

        create_paper_related_tags(
            paper_data["paper"],
            paper_data["openalex_concepts"],
            paper_data["openalex_topics"],
        )

    # Process authorships with fetched author data
    for paper_id, paper_data in paper_to_openalex_data.items():
        work = paper_data["openalex_work"]
        openalex_authorships = work.get("authorships")
        if openalex_authorships and paper_id:
            try:
                process_openalex_authorships(openalex_authorships, paper_id, oa_authors)
            except Exception as e:
                sentry.log_error(
                    e, message=f"Failed to process authorships for paper_id: {paper_id}"
                )
        else:
            sentry.log_error(
                None,
                message=f"Authorships data is missing or paper_id is None for work: {work.get('id')}",
            )


def fetch_authors_for_works(openalex_works):
    open_alex = OpenAlex()
    all_authors_to_fetch = set()
    oa_authors = []

    for work in openalex_works:
        oa_authorships = work.get("authorships", [])
        for oa_authorship in oa_authorships:
            author_openalex_id = oa_authorship.get("author", {}).get("id")
            just_id = author_openalex_id.split("/")[-1]
            all_authors_to_fetch.add(just_id)

    next_cursor = "*"
    while next_cursor is not None:
        oa_authors_batch, next_cursor = open_alex.get_authors(
            openalex_ids=list(all_authors_to_fetch)
        )
        oa_authors.extend(oa_authors_batch)

        if oa_authors_batch is None and len(oa_authors_batch) == 0:
            break

    return oa_authors


def process_openalex_authorships(openalex_authorships, related_paper_id, oa_authors):
    """
    Iterates through authorships associated with an OpenAlex work and create related objects such as
    AuthorInstitution, Authorship, and Author objects. Related models will be updated if they already exist.
    https://docs.openalex.org/api-entities/works/work-object/authorship-object
    """
    from institution.models import Institution
    from paper.models import Paper
    from paper.related_models.authorship_model import Authorship
    from purchase.models import Wallet
    from user.related_models.author_model import Author

    related_paper = Paper.objects.get(id=related_paper_id)
    print(f"Processing authorships for paper: {related_paper.title}")
    authors_in_this_work = []
    all_openalex_ids = [
        oa_authorship.get("author", {}).get("id")
        for oa_authorship in openalex_authorships
    ]
    authors = Author.objects.filter(openalex_ids__overlap=all_openalex_ids)

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
        if len(authors) == 0:
            author_name_parts = (
                oa_authorship.get("author", {}).get("display_name").split(" ")
            )
            author = Author.objects.create(
                first_name=author_name_parts[0],
                last_name=author_name_parts[-1],
                openalex_ids=[author_openalex_id],
                created_source=Author.SOURCE_OPENALEX,
            )
            Wallet.objects.create(author=author)
            authors.append(author)

        for author in authors:
            # Associate paper with author
            related_paper.authors.add(author)

            is_corresponding = oa_authorship.get("is_corresponding")
            raw_author_name = oa_authorship.get("author", {}).get("display_name")

            # Find or create authorship
            authorship, _ = Authorship.objects.get_or_create(
                author=author,
                paper=related_paper,
                defaults={
                    "author_position": author_position,
                    "is_corresponding": is_corresponding,
                    "raw_author_name": raw_author_name,
                },
            )

            # Update authorship if secondary fields have changed
            if (
                authorship.author_position != author_position
                or authorship.is_corresponding != is_corresponding
                or authorship.raw_author_name != raw_author_name
            ):
                authorship.author_position = author_position
                authorship.is_corresponding = is_corresponding
                authorship.raw_author_name = raw_author_name
                authorship.save()

            authors_in_this_work.append(author)

            # Set institutions associated with authorships if they do not already exist
            for oa_inst in oa_authorship.get("institutions", []):
                institution = Institution.upsert_from_openalex(oa_inst)
                if institution:
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
        for coauthor in authors_in_this_work:
            if author != coauthor:
                coauthor_objects.append(
                    CoAuthor(
                        author=author, coauthor=coauthor, paper_id=related_paper_id
                    )
                )

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
