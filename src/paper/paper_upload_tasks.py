import re
from collections import Counter
from json.decoder import JSONDecodeError
from unicodedata import normalize
from urllib.parse import urlparse

import cloudscraper
from bs4 import BeautifulSoup
from celery import chain, chord
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger
from cloudscraper.exceptions import CloudflareChallengeError
from django.apps import apps
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.postgres.search import SearchQuery
from django.core.exceptions import ValidationError
from django.db.models import Q
from habanero import Crossref
from requests.exceptions import HTTPError

from citation.models import CitationEntry
from hub.models import Hub
from paper.exceptions import (
    DOINotFoundError,
    DuplicatePaperError,
    ManubotProcessingError,
)
from paper.tasks import add_orcid_authors, download_pdf
from paper.utils import (
    DOI_REGEX,
    clean_abstract,
    clean_dois,
    format_raw_authors,
    get_csl_item,
    get_pdf_location_for_csl_item,
)
from researchhub.celery import QUEUE_PAPER_METADATA, app
from researchhub_document.related_models.constants.document_type import (
    FILTER_OPEN_ACCESS,
)
from tag.models import Concept
from utils import sentry
from utils.http import check_url_contains_pdf
from utils.openalex import OpenAlex
from utils.semantic_scholar import SemanticScholar
from utils.unpaywall import Unpaywall

logger = get_task_logger(__name__)


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_process_paper(self, submission_id):
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    paper_submission = PaperSubmission.objects.get(id=submission_id)
    paper_submission.set_processing_status()
    paper_submission.notify_status()
    uploaded_by = paper_submission.uploaded_by
    url = paper_submission.url
    doi = paper_submission.doi
    citation = paper_submission.citation

    celery_data = {
        "url": url,
        "uploaded_by_id": uploaded_by.id,
        "submission_id": submission_id,
    }
    if citation is not None:
        celery_data["citation_id"] = citation.id
    args = (celery_data, submission_id)

    apis = []
    if doi:
        celery_data["doi"] = doi

        apis.extend(
            [
                celery_unpaywall.s(),
                celery_openalex.s(),
                celery_crossref.s(),
                celery_semantic_scholar.s(),
            ]
        )

    tasks = []
    if url:
        tasks.extend(
            [
                chord(
                    [celery_get_doi.s(), celery_manubot_doi.s()], celery_combine_doi.s()
                ).on_error(celery_handle_paper_processing_errors.s()),
            ]
        )
        apis.append(celery_manubot.s())
        apis.append(celery_openalex.s())
    else:
        celery_data.pop("url")

    tasks.extend(
        [
            chord(apis, celery_combine_paper_data.s()).on_error(
                celery_handle_paper_processing_errors.s()
            ),
            celery_create_paper.s().set(countdown=0.5),
        ]
    )

    workflow = chain(tasks)
    res = workflow(args)
    return res


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_get_doi(self, celery_data):
    paper_data, submission_id = celery_data
    try:
        url = paper_data["url"]
        parsed_url = urlparse(url)
        scraper = cloudscraper.create_scraper()
        res = scraper.get(url)
        status_code = res.status_code
        dois = []

        if status_code >= 200 and status_code < 400:
            content = BeautifulSoup(res.content, "lxml")
            dois = re.findall(DOI_REGEX, str(content))
            dois = list(map(str.strip, dois))
            dois = clean_dois(parsed_url, dois)

            doi_counter = Counter(dois)
            dois = [doi for doi, _ in doi_counter.most_common(1)]

        response = {**paper_data, "dois": dois, "submission_id": submission_id}
        return response
    except CloudflareChallengeError as e:
        self.request.args = (celery_data, submission_id)
        return {"error": str(e), "submission_id": submission_id}
    except Exception as e:
        self.request.args = (celery_data, submission_id)
        return {"error": str(e), "submission_id": submission_id}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_manubot_doi(self, celery_data):
    paper_data, submission_id = celery_data

    try:
        url = paper_data["url"]
        csl_item = get_csl_item(url)
        doi = csl_item.get("DOI", None)

        dois = []
        if doi:
            dois = [doi]
        elif "science.org" in url:
            doi = url.split("science.org/doi/")[1].replace("pdf/", "")
            dois = [doi]

        response = {**paper_data, "dois": dois, "submission_id": submission_id}

        return response
    except ManubotProcessingError as e:
        self.request.args = (celery_data, submission_id)
        return {"error": str(e), "submission_id": submission_id}
    except Exception as e:
        self.request.args = (celery_data, submission_id)
        return {"error": str(e), "submission_id": submission_id}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_combine_doi(self, celery_data):
    Paper = apps.get_model("paper.Paper")
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    try:
        dois = []
        errors = []

        for doi_data in celery_data:
            submission_id = doi_data.get("submission_id")
            if "error" in doi_data:
                error = doi_data.get("error")
                errors.append(error)
                continue
            else:
                doi_list = doi_data.pop("dois", [])
                dois.extend(doi_list)

        paper_submission = PaperSubmission.objects.get(id=submission_id)
        if dois:
            doi = dois[0]
            paper_submission.doi = doi
            paper_submission.save()
        else:
            for error in errors:
                sentry.log_info(error)
            self.request.args = (celery_data, submission_id)
            raise DOINotFoundError()

        paper_submission.set_processing_doi_status()
        doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
        if doi_paper_check.exists():
            duplicate_ids = doi_paper_check.values_list("id", flat=True)
            paper_submission.set_duplicate_status()
            self.request.args = (celery_data, submission_id)
            raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

        if errors:
            sentry.log_info(errors)

    except DOINotFoundError as e:
        raise e
    except DuplicatePaperError as e:
        raise e

    response = ({**doi_data, "doi": doi, "submission_id": submission_id}, submission_id)
    return response


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_manubot(self, celery_data):
    paper_data, submission_id = celery_data

    Paper = apps.get_model("paper.Paper")

    try:
        doi = paper_data.get("doi")
        url = paper_data.get("url")

        csl_item = get_csl_item(url)
        doi = csl_item.get("DOI", None)
        identifier = csl_item.get("id", None)

        # DOI duplicate check
        if doi:
            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
            if doi_paper_check.exists():
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)
        else:
            doi = identifier

        # Url duplicate check
        oa_pdf_location = get_pdf_location_for_csl_item(csl_item)
        csl_item["oa_pdf_location"] = oa_pdf_location
        urls = [url]
        if oa_pdf_location:
            oa_url = oa_pdf_location.get("url", [])
            oa_landing_page_url = oa_pdf_location.get("url_for_landing_page", [])
            oa_pdf_url = oa_pdf_location.get("url_for_pdf", [])

            urls.extend([oa_url])
            urls.extend([oa_landing_page_url])
            urls.extend([oa_pdf_url])

        for url_check in urls:
            url_paper_check = Paper.objects.filter(
                Q(url_svf=SearchQuery(url_check))
                | Q(pdf_url_svf=SearchQuery(url_check))
            )
            if url_paper_check.exists():
                duplicate_ids = url_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate URL: {urls}", duplicate_ids)

        # Cleaning csl data
        cleaned_title = csl_item.get("title", "").strip()
        abstract = csl_item.get("abstract", "")
        cleaned_abstract = clean_abstract(abstract)
        publish_date = csl_item.get_date("issued", fill=True)
        raw_authors = csl_item.get("author", [])
        raw_authors = format_raw_authors(raw_authors)

        data = {
            "abstract": cleaned_abstract,
            "csl_item": csl_item,
            "doi": doi,
            "paper_publish_date": publish_date,
            "raw_authors": raw_authors,
            "title": cleaned_title,
            "paper_title": cleaned_title,
            "url": url,
        }

        if oa_pdf_location:
            if oa_pdf_url:
                data["pdf_url"] = oa_pdf_url

            license = oa_pdf_location.get("license", None)
            data["pdf_license"] = license

        response = {
            **paper_data,
            "data": data,
            "key": 5,
            "submission_id": submission_id,
        }
        return response
    except DuplicatePaperError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except ManubotProcessingError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except Exception as e:
        return {"error": str(e), "key": 10, **paper_data}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_unpaywall(self, celery_data):
    paper_data, submission_id = celery_data

    Paper = apps.get_model("paper.Paper")

    try:
        doi = paper_data.get("doi")
        unpaywall = Unpaywall()
        result = unpaywall.search_by_doi(doi)

        if result:
            # Duplicate DOI check
            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
            if doi_paper_check.exists():
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

            oa_locations = result.get("oa_locations", [])

            for oa_location in oa_locations:
                oa_pdf_url = oa_location.get("url_for_pdf", "")
                if oa_pdf_url and check_url_contains_pdf(oa_pdf_url):
                    paper_data.setdefault("pdf_url", oa_pdf_url)
                    paper_data.setdefault(
                        "pdf_license", oa_location.get("license", None)
                    )
                    paper_data.setdefault("pdf_license_url", oa_pdf_url)
                    break

            title = normalize("NFKD", result.get("title", ""))
            raw_authors = result.get("z_authors", [])
            data = {
                "url": result.get("doi_url", None),
                "raw_authors": format_raw_authors(raw_authors),
                "title": title,
                "doi": doi,
                "paper_title": title,
                "is_open_access": result.get("is_oa", False),
                "oa_status": result.get("oa_status", None),
                "external_source": result.get("publisher", None),
                "paper_publish_date": result.get("published_date", None),
            }
            response = {
                **paper_data,
                "data": data,
                "key": 1,
                "submission_id": submission_id,
            }

            return response
        return celery_data
    except DOINotFoundError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except DuplicatePaperError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except Exception as e:
        return {"error": str(e), "key": 10, **paper_data}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_crossref(self, celery_data):
    paper_data, submission_id = celery_data

    Paper = apps.get_model("paper.Paper")

    try:
        doi = paper_data.get("doi")
        url = paper_data.get("url")

        cr = Crossref()
        params = {
            "filters": {"type": "journal-article"},
            "ids": [doi],
        }
        results = cr.works(**params).get("message")

        if results:
            # Duplicate DOI check
            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
            if doi_paper_check.exists():
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

            abstract = clean_abstract(results.get("abstract", ""))
            raw_authors = results.get("author", [])
            title = normalize("NFKD", results.get("title", [])[0])

            data = {
                "doi": doi,
                "url": url,
                "abstract": abstract,
                "raw_authors": format_raw_authors(raw_authors),
                "title": title,
                "paper_title": title,
            }
            response = {
                **paper_data,
                "data": data,
                "key": 4,
                "submission_id": submission_id,
            }
            return response

        return celery_data
    except DOINotFoundError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except DuplicatePaperError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except (HTTPError, JSONDecodeError) as e:
        return {"error": str(e), "key": 10, **paper_data}
    except Exception as e:
        return {"error": str(e), "key": 10, **paper_data}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_openalex(self, celery_data):
    paper_data, submission_id = celery_data

    Paper = apps.get_model("paper.Paper")

    try:
        doi = paper_data.get("doi")
        open_alex = OpenAlex()
        result = open_alex.get_data_from_doi(doi)

        if result:
            # Duplicate DOI check
            doi = paper_data["doi"]
            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
            if doi_paper_check.exists():
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

            host_venue = result.get("host_venue", {})
            oa = result.get("open_access", {})
            oa_pdf_url = oa.get("oa_url", None)
            url = host_venue.get("url", None)
            title = normalize("NFKD", result.get("title", ""))
            raw_authors = result.get("authorships", [])
            concepts = result.get("concepts", [])

            data = {
                "doi": doi,
                "url": url,
                "raw_authors": format_raw_authors(raw_authors),
                "title": title,
                "paper_title": title,
                "paper_publish_date": result.get("publication_date", None),
                "is_open_access": oa.get("is_oa", None),
                "oa_status": oa.get("oa_status", None),
                "pdf_license": host_venue.get("license", None),
                "pdf_license_url": url,
                "external_source": host_venue.get("display_name", None),
            }

            if oa_pdf_url and check_url_contains_pdf(oa_pdf_url):
                data["pdf_url"] = oa_pdf_url

            paper_concepts = open_alex.hydrate_paper_concepts(concepts)
            data["concepts"] = paper_concepts
            response = {
                **paper_data,
                "data": data,
                "key": 2,
                "submission_id": submission_id,
            }
            return response

        return celery_data
    except DOINotFoundError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except DuplicatePaperError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except Exception as e:
        return {"error": str(e), "key": 10, **paper_data}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_semantic_scholar(self, celery_data):
    paper_data, submission_id = celery_data

    Paper = apps.get_model("paper.Paper")

    try:
        doi = paper_data.get("doi")
        url = paper_data.get("url")
        semantic_scholar = SemanticScholar()
        result = semantic_scholar.get_data_from_doi(doi)

        if result:
            # Duplicate DOI check
            doi = paper_data["doi"]
            doi_paper_check = Paper.objects.filter(doi_svf=SearchQuery(doi))
            if doi_paper_check.exists():
                duplicate_ids = doi_paper_check.values_list("id", flat=True)
                raise DuplicatePaperError(f"Duplicate DOI: {doi}", duplicate_ids)

            abstract = clean_abstract(result.get("abstract", ""))
            title = normalize("NFKD", result.get("title", ""))
            raw_authors = result.get("authors", [])
            data = {
                "doi": doi,
                "url": url,
                "abstract": abstract,
                "raw_authors": format_raw_authors(raw_authors),
                "title": title,
                "paper_title": title,
                "is_open_access": result.get("isOpenAccess", False),
                "paper_publish_date": result.get("publicationDate", None),
            }
            response = {
                **paper_data,
                "data": data,
                "key": 3,
                "submission_id": submission_id,
            }
            return response
        return celery_data
    except DOINotFoundError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except DuplicatePaperError as e:
        return {"error": str(e), "key": 10, **paper_data}
    except Exception as e:
        return {"error": str(e), "key": 10, **paper_data}


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_combine_paper_data(self, celery_data):
    PaperSubmission = apps.get_model("paper.PaperSubmission")

    errors = []
    data = {}
    sorted_data = sorted(celery_data, key=lambda data: data["key"])
    for combined_data in sorted_data:
        if "submission_id" in combined_data:
            submission_id = combined_data.get("submission_id")
        if "error" in combined_data:
            error = combined_data.get("error")
            errors.append(error)
            continue

        paper_data = combined_data.get("data")
        uploaded_by_id = combined_data.get("uploaded_by_id")
        if uploaded_by_id:
            data["uploaded_by_id"] = uploaded_by_id
        for key, value in paper_data.items():
            if value is not None:
                data.setdefault(key, value)

        paper_submission = PaperSubmission.objects.get(id=submission_id)
        paper_submission.doi = data.get("doi")
        paper_submission.save()
        paper_submission.set_processing_doi_status()

    if errors:
        sentry.log_info(errors)

    if not data:
        self.request.args = (celery_data, submission_id)
        raise DOINotFoundError("Unable to find article")

    return (data, submission_id, combined_data.get("citation_id", None))


@app.task(bind=True, queue=QUEUE_PAPER_METADATA, ignore_result=False)
def celery_create_paper(self, celery_data):
    from reputation.tasks import create_contribution

    paper_data, submission_id, citation_id = celery_data

    Paper = apps.get_model("paper.Paper")
    PaperSubmission = apps.get_model("paper.PaperSubmission")
    Contribution = apps.get_model("reputation.Contribution")
    paper_concepts = paper_data.pop("concepts", [])

    try:
        paper_submission = PaperSubmission.objects.get(id=submission_id)
        dois = paper_data.pop("dois", None)
        if dois:
            raise DOINotFoundError(
                f"Unable to find article for: {dois}, {paper_submission.url}"
            )

        async_paper_updator = getattr(paper_submission, "async_updator", None)
        paper = Paper(**paper_data)
        if async_paper_updator is not None:
            paper.doi = async_paper_updator.doi
            paper.unified_document.hubs.add(*async_paper_updator.hubs)
            paper.title = async_paper_updator.title
            # Used for backwards compatibility. Hubs should preferrably be retrieved through the unified_document model.
            paper.hub.add(*async_paper_updator.hubs)

        paper.full_clean()
        paper.get_abstract_backup(should_save=False)
        paper.get_pdf_link(should_save=False)
        paper.save()

        paper_id = paper.id
        paper_submission.set_complete_status(save=False)
        paper_submission.paper = paper
        paper_submission.save()

        if citation_id:
            citation = CitationEntry.objects.get(id=citation_id)
            citation.related_unified_doc = paper.unified_document
            citation.save()

        uploaded_by = paper_submission.uploaded_by

        from discussion.models import Vote as GrmVote

        GrmVote.objects.create(
            content_type=get_content_type_for_model(paper),
            created_by=uploaded_by,
            object_id=paper.id,
            vote_type=GrmVote.UPVOTE,
        )
        paper.unified_document.update_filter(FILTER_OPEN_ACCESS)
        download_pdf.apply_async((paper_id,), priority=3, countdown=5)
        add_orcid_authors.apply_async((paper_id,), priority=5, countdown=5)
        create_contribution.apply_async(
            (
                Contribution.SUBMITTER,
                {"app_label": "paper", "model": "paper"},
                uploaded_by.id,
                paper.unified_document.id,
                paper_id,
            ),
            priority=2,
            countdown=3,
        )
        paper_submission.notify_status()
    except ValidationError as e:
        raise e
    except Exception as e:
        raise e

    hubs_to_tag_paper_with = []
    for paper_concept in paper_concepts:
        try:
            logger.info(f"concepts in celery_create_paper: {paper_concepts}")

            # Every time a concept is created, an associated hub is also created
            concept = Concept.create_or_update(paper_concept)
            paper.unified_document.concepts.add(
                concept,
                through_defaults={
                    "relevancy_score": paper_concept["score"],
                    "level": paper_concept["level"],
                },
            )

            hubs_to_tag_paper_with.append(concept.hub)
        except Exception as e:
            print("Failed to save concepts fo paper" + str(paper.id))
            print(
                {
                    "concept": concept,
                    "paper_concept": paper_concept,
                }
            )
            sentry.log_error(
                e,
                message={
                    "concept": concept,
                    "paper_concept": paper_concept,
                },
            )

    if len(hubs_to_tag_paper_with) > 0:
        paper.unified_document.hubs.add(*hubs_to_tag_paper_with)
        paper.hubs.add(*hubs_to_tag_paper_with)

    return paper_id


@app.task(queue=QUEUE_PAPER_METADATA)
def celery_handle_paper_processing_errors(request, exc, traceback):
    try:
        sentry.log_error(exc)

        extra_metadata = {}
        PaperSubmission = apps.get_model("paper.PaperSubmission")
        celery_args = request.args
        _, submission_id = celery_args
        paper_submission = PaperSubmission.objects.get(id=submission_id)

        if isinstance(exc, DuplicatePaperError):
            duplicate_ids = exc.args[1]
            extra_metadata["duplicate_ids"] = list(duplicate_ids)
            paper_submission.set_duplicate_status()
        elif isinstance(exc, SoftTimeLimitExceeded):
            paper_submission.set_failed_timeout_status()
        elif isinstance(exc, DOINotFoundError):
            paper_submission.set_failed_doi_status()
        else:
            paper_submission.set_failed_status()

        paper_submission.notify_status(**extra_metadata)
    except Exception as e:
        sentry.log_error(e, exc)

    return
