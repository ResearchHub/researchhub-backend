import logging

from django.apps import apps
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q

import utils.sentry as sentry
from paper.utils import get_cache_key
from purchase.models import Wallet
from tag.models import Concept
from utils.http import check_url_contains_pdf
from utils.openalex import OpenAlex


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

    paper_to_topics_and_concepts = {}

    # Create new papers
    with transaction.atomic():
        for work in create_papers:
            (
                data,
                openalex_concepts,
                openalex_topics,
            ) = open_alex.build_paper_from_openalex_work(work)

            # concepts = openalex_concepts  # open_alex.hydrate_paper_concepts(openalex_concepts)
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

    # Only these particular fields will be updated
    fields_to_update = [
        "paper_publish_date",
        "alternate_ids",
        "citations",
        "abstract",
        "pdf_license",
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
    ]

    # Prepare papers for batch update
    for existing_paper, work in update_papers:
        (
            data,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(work)

        # we didn't fetch all fields in the initial paper query (we used .only()),
        # so we need to explicitly fetch them if we want to update them.
        # otherwise django doesn't update them, e.g. paper_publish_date
        existing_paper.refresh_from_db(fields=[*fields_to_update])

        for field in fields_to_update:
            setattr(existing_paper, field, data.get(field))

        paper_to_topics_and_concepts[existing_paper.id] = (
            openalex_concepts,
            openalex_topics,
        )

    # perform batch update
    if update_papers and len(update_papers) > 0:
        fields_to_update = [*fields_to_update]
        papers_to_update = [paper for paper, _ in update_papers]
        try:
            Paper.objects.bulk_update(papers_to_update, fields_to_update)
        except Exception as e:
            sentry.log_error(e, message="Failed to bulk update papers")

    # Upsert concepts and associate to papers
    for paper_id, topics_and_concepts in paper_to_topics_and_concepts.items():
        openalex_concepts, openalex_topics = topics_and_concepts
        create_paper_related_tags(paper_id, openalex_concepts, openalex_topics)
