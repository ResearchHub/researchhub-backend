import copy
import logging

from django.apps import apps
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

import utils.sentry as sentry
from paper.utils import get_cache_key
from utils.http import check_url_contains_pdf
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
    from institution.models import Institution
    from paper.models import Paper
    from paper.paper_upload_tasks import create_paper_related_tags
    from paper.related_models.authorship_model import Authorship
    from purchase.models import Wallet
    from tag.models import Concept
    from user.related_models.author_model import Author

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
    with transaction.atomic():
        for work in create_papers:
            _work = copy.deepcopy(work)

            (
                data,
                openalex_concepts,
                openalex_topics,
            ) = open_alex.build_paper_from_openalex_work(_work)

            paper = Paper(**data)

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
            except IntegrityError as e:
                sentry.log_error(
                    e, message=f"Failed to save paper, DOI already exists: {paper.doi}"
                )
            except Exception as e:
                sentry.log_error(
                    e, message=f"Failed to save paper, unexpected error: {paper.doi}"
                )

            paper_to_openalex_data[paper.id] = {
                "openalex_concepts": openalex_concepts,
                "openalex_topics": openalex_topics,
                "openalex_work": work,
            }

    # Prepare papers for batch update
    for existing_paper, work in update_papers:
        _work = copy.deepcopy(work)
        (
            data,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(_work)

        # we didn't fetch all fields in the initial paper query (we used .only()),
        # so we need to explicitly fetch them if we want to update them.
        # otherwise django doesn't update them, e.g. paper_publish_date
        existing_paper.refresh_from_db(fields=[*PAPER_FIELDS_ALLOWED_TO_UPDATE])

        for field in PAPER_FIELDS_ALLOWED_TO_UPDATE:
            setattr(existing_paper, field, data.get(field))

        paper_to_openalex_data[existing_paper.id] = {
            "openalex_concepts": openalex_concepts,
            "openalex_topics": openalex_topics,
            "openalex_work": work,
        }

    # perform batch update
    if update_papers and len(update_papers) > 0:
        fields_to_update = [*PAPER_FIELDS_ALLOWED_TO_UPDATE]
        papers_to_update = [paper for paper, _ in update_papers]
        try:
            Paper.objects.bulk_update(papers_to_update, fields_to_update)
        except Exception as e:
            sentry.log_error(e, message="Failed to bulk update papers")

    # Upsert concepts and associate to papers
    for paper_id, paper_data in paper_to_openalex_data.items():
        create_paper_related_tags(
            paper_id, paper_data["openalex_concepts"], paper_data["openalex_topics"]
        )

        openalex_authorships = paper_data["openalex_work"].get("authorships")

        for oa_authorship in openalex_authorships:
            author_position = oa_authorship.get("author_position")
            author_openalex_id = oa_authorship.get("author", {}).get("id")

            author = None
            try:
                author = Author.objects.get(openalex_ids__contains=[author_openalex_id])
            except Author.DoesNotExist:
                author_name_parts = (
                    oa_authorship.get("author", {}).get("display_name").split(" ")
                )
                author = Author.objects.create(
                    first_name=author_name_parts[0],
                    last_name=author_name_parts[-1],
                    openalex_ids=[author_openalex_id],
                )
                Wallet.objects.create(author=author)

            # Create authorship
            affiliated_institutions = Institution.objects.filter(
                openalex_id__in=[
                    inst["id"] for inst in oa_authorship.get("institutions", [])
                ]
            )

            # Find or create authorship
            authorship, created = Authorship.objects.get_or_create(
                author=author,
                author_position=author_position,
                paper_id=paper_id,
                is_corresponding=oa_authorship.get("is_corresponding"),
                raw_author_name=oa_authorship.get("author", {}).get("display_name"),
            )

            # Get affiliated institutions
            affiliated_institutions = Institution.objects.filter(
                openalex_id__in=[
                    inst["id"] for inst in oa_authorship.get("institutions", [])
                ]
            )

            # Set institutions to authorship if they are not already set
            existing_institutions = authorship.institutions.all()
            new_institutions = [
                inst
                for inst in affiliated_institutions
                if inst not in existing_institutions
            ]

            if new_institutions:
                authorship.institutions.add(*new_institutions)
