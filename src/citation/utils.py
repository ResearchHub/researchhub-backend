from urllib.parse import urlparse

import pdf2doi
import requests
from django.contrib.postgres.search import SearchQuery
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Q
from django.http.request import HttpRequest
from rest_framework.request import Request

from citation.constants import JOURNAL_ARTICLE
from citation.exceptions import GrobidProcessingError
from citation.models import CitationEntry
from citation.schema import (
    generate_json_for_doi_via_oa,
    generate_json_for_pdf,
    generate_json_for_rh_paper,
)
from citation.serializers import CitationEntrySerializer
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers import PaperSubmissionSerializer
from researchhub.settings import AWS_STORAGE_BUCKET_NAME, GROBID_SERVER
from user.models import User
from utils.parsers import get_pure_doi
from utils.sentry import log_error


def get_pdf_header_data(path):
    url = f"{GROBID_SERVER}/header_extract"
    request_data = {
        "s3_file_path": f"{path}",
        "bucket_name": f"{AWS_STORAGE_BUCKET_NAME}",
    }
    try:
        response = requests.post(url, data=request_data, timeout=10)
        data = response.json()
        status = data.get("status")
        if status == 200:
            return data.get("data", {})
    except requests.ConnectionError as e:
        log_error(e)
        raise GrobidProcessingError(e, "GROBID - Request to Grobid server timed out")

    raise GrobidProcessingError(
        "GROBID - Could not extract data", "Grobid queue is most likely full"
    )


def get_citation_entry_from_pdf(
    path, filename, user_id, organization_id, project_id, use_grobid
):
    pdf = None
    if use_grobid:
        header_data = get_pdf_header_data(path)
        doi = header_data.get("doi", None)
    else:
        pdf = default_storage.open(path)
        header_data = pdf2doi.pdf2doi_singlefile(pdf)
        doi = header_data.get("identifier")

    citation_entry = CitationEntry.objects.filter(
        doi=doi,
        created_by=user_id,
        project_id=project_id,
        organization_id=organization_id,
    )
    if doi is None or not citation_entry.exists():
        with transaction.atomic():
            # CitationEntrySerializer inherits from DefaultAuthenticatedSerializer,
            # which requires a request object with a user attached
            request = Request(HttpRequest())
            request.user = User.objects.get(id=user_id)

            related_unified_doc = None
            if pdf is None:
                pdf = default_storage.open(path)

            if not doi:
                pdf.name = filename
                json = generate_json_for_pdf(filename)
            else:
                try:
                    paper = get_paper_by_doi(doi)
                    json = generate_json_for_rh_paper(paper)
                    related_unified_doc = paper.unified_document.id
                except Paper.DoesNotExist:
                    json = generate_json_for_doi_via_oa(doi)
                except Exception as e:
                    log_error(e)
                    pdf.name = filename
                    json = generate_json_for_pdf(filename)

            citation_entry_data = {
                "citation_type": JOURNAL_ARTICLE,
                "fields": json,
                "created_by": user_id,
                "organization": organization_id,
                "attachment": pdf,
                "doi": doi,
                "project": project_id,
                "related_unified_doc": related_unified_doc,
            }
            context = {"request": request}
            serializer = CitationEntrySerializer(
                data=citation_entry_data, context=context
            )
            serializer.is_valid(raise_exception=True)
            entry = serializer.save()
            create_paper_from_citation(entry)
            default_storage.delete(path)
            return entry, False
    else:
        return citation_entry.first(), True


def create_paper_from_citation(citation):
    doi = citation.doi

    if doi is None:
        return

    pure_doi = get_pure_doi(doi)

    # Appends http if protocol does not exist
    parsed_url = urlparse(doi)
    if not parsed_url.scheme:
        url = f"http://{parsed_url.geturl()}"
    else:
        url = doi

    url_search_query = SearchQuery(url)
    duplicate_papers = Paper.objects.filter(
        Q(url_svf=url_search_query) | Q(pdf_url_svf=url_search_query)
    )

    process_id = None

    if not duplicate_papers:
        data = {
            # "uploaded_by": citation.created_by.id,
            "uploaded_by": None,
            "citation": citation.id,
            "doi": pure_doi,
        }
        submission = PaperSubmissionSerializer(data=data)
        if submission.is_valid():
            submission = submission.save()
            process_id = celery_process_paper(submission.id)
    else:
        print("duplicate paper with doi {}".format(citation.doi))

    return {"duplicate": duplicate_papers.exists(), "process_id": process_id}


def get_paper_by_svf(key, query):
    search_query = SearchQuery(query)
    return Paper.objects.get(**{key: search_query})


def get_paper_by_doi(doi):
    return get_paper_by_svf("doi_svf", doi)


def get_paper_by_url(url):
    return get_paper_by_svf("url_svf", url) or get_paper_by_svf("pdf_url_svf", url)
