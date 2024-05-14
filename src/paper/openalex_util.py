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
            print(f"No Doi for result: {work}")
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
    paper_ids_to_add_to_biorxiv_hub = []

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
                sentry.log_error(e, message=f"Failed to validate paper: {paper.doi}")
                continue

            # paper.get_pdf_link()

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

            # if the paper is from biorXiv, we want to add it to the biorXiv Community Reviews hub
            # so that it can get auto-assigned a peer-review with enough upvotes.
            if "bioRxiv" in paper.external_source:
                paper_ids_to_add_to_biorxiv_hub.append(paper.id)

            paper_to_topics_and_concepts[paper.id] = (
                openalex_concepts,
                openalex_topics,
            )

    # batch create authors
    # if new_paper_ids and len(new_paper_ids) > 0:
    #     try:
    #         add_orcid_authors(new_paper_ids)
    #     except Exception as e:
    #         sentry.log_error(e, message="Failed to batch create authors")

    # Prepare papers for batch update
    for existing_paper, work in update_papers:
        (
            data,
            openalex_concepts,
            openalex_topics,
        ) = open_alex.build_paper_from_openalex_work(work)

        # concepts = openalex_concepts  # open_alex.hydrate_paper_concepts(openalex_concepts)

        # we didn't fetch all fields in the initial paper query (we used .only()),
        # so we need to explicitly fetch them if we want to update them.
        # otherwise django doesn't update them, e.g. paper_publish_date
        existing_paper.refresh_from_db(
            fields=[
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
        )

        existing_paper.paper_publish_date = data.get("paper_publish_date")
        existing_paper.alternate_ids = data.get("alternate_ids", {})
        existing_paper.citations = data.get("citations")
        existing_paper.openalex_id = data.get("openalex_id")
        existing_paper.is_retracted = data.get("is_retracted")
        existing_paper.mag_id = data.get("mag_id")
        existing_paper.pubmed_id = data.get("pubmed_id")
        existing_paper.pubmed_central_id = data.get("pubmed_central_id")
        existing_paper.work_type = data.get("work_type")
        existing_paper.language = data.get("language")

        if existing_paper.abstract is None:
            existing_paper.abstract = data.get("abstract")
        if data.get("pdf_license") is not None:
            existing_paper.pdf_license = data.get("pdf_license")
        if data.get("oa_status") is not None:
            existing_paper.oa_status = data.get("oa_status")
        existing_paper.is_open_access = data.get("is_open_access")
        existing_paper.open_alex_raw_json = data.get("open_alex_raw_json")

        paper_to_topics_and_concepts[existing_paper.id] = (
            openalex_concepts,
            openalex_topics,
        )

        # if the paper is from biorXiv, we want to add it to the biorXiv Community Reviews hub
        # so that it can get auto-assigned a peer-review with enough upvotes.
        if "bioRxiv" in existing_paper.external_source:
            paper_ids_to_add_to_biorxiv_hub.append(existing_paper.id)

    # perform batch update
    if update_papers and len(update_papers) > 0:
        fields_to_update = [
            "paper_publish_date",
            "alternate_ids",
            "citations",
            "abstract",
            "pdf_license",
            "oa_status",
            "is_open_access",
            "open_alex_raw_json",
            "openalex_id",
            "is_retracted",
            "mag_id",
            "pubmed_id",
            "pubmed_central_id",
            "work_type",
            "language",
        ]
        papers_to_update = [paper for paper, _ in update_papers]
        try:
            Paper.objects.bulk_update(papers_to_update, fields_to_update)
        except Exception as e:
            sentry.log_error(e, message="Failed to bulk update papers")

    # batch add papers to biorXiv hub
    if paper_ids_to_add_to_biorxiv_hub and len(paper_ids_to_add_to_biorxiv_hub) > 0:
        # batch fetch papers
        papers_to_add_to_biorxiv_hub = Paper.objects.filter(
            id__in=paper_ids_to_add_to_biorxiv_hub
        ).only("id", "unified_document", "hubs")

        with transaction.atomic():
            biorxiv_hub_id = 436

            for paper in papers_to_add_to_biorxiv_hub:
                try:
                    paper.hubs.add(biorxiv_hub_id)
                    paper.unified_document.hubs.add(biorxiv_hub_id)
                except Exception as e:
                    sentry.log_error(
                        e, message=f"Failed to add paper to biorXiv hub: {paper.id}"
                    )
                    continue

    # Upsert concepts and associate to papers
    for paper_id, topics_and_concepts in paper_to_topics_and_concepts.items():
        openalex_concepts, openalex_topics = topics_and_concepts
        create_paper_related_tags(paper_id, openalex_concepts, openalex_topics)
