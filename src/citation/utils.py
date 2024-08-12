from urllib.parse import urlparse

import pdf2doi
from django.contrib.postgres.search import SearchQuery
from django.core.files.storage import default_storage
from django.db import transaction
from django.http.request import HttpRequest
from rest_framework.request import Request

from citation.constants import BIBTEX_TO_CITATION_TYPES, JOURNAL_ARTICLE
from citation.models import CitationEntry
from citation.schema import (
    generate_json_for_bibtex_entry,
    generate_json_for_doi_via_oa,
    generate_json_for_pdf,
    generate_json_for_rh_paper,
    merge_jsons,
)
from citation.serializers import CitationEntrySerializer
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers import PaperSubmissionSerializer
from paper.utils import download_pdf, pdf_copyright_allows_display
from user.models import User
from utils.aws import lambda_compress_and_linearize_pdf
from utils.bibtex import BibTeXEntry
from utils.openalex import OpenAlex
from utils.parsers import get_pure_doi
from utils.sentry import log_error


def get_citation_entry_from_pdf(path, filename, user_id, organization_id, project_id):
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

            key = entry.attachment.name
            lambda_compress_and_linearize_pdf(key, filename)
            return entry, False
    else:
        return citation_entry.first(), True


def create_citation_entry_from_bibtex_entry_if_not_exists(
    bibtex_entry: BibTeXEntry, user_id, organization_id, project_id
):
    """
    Creates a citation entry from a bibtex entry if it doesn't already exist.
    Returns:
        (citation_entry, already_exists, error_message)
        - error_message: Ideally a user-friendly string
    """
    doi = bibtex_entry.fields_dict.get("doi", None)

    citation_entry = CitationEntry.objects.filter(
        doi=doi,
        created_by=user_id,
        project_id=project_id,
        organization_id=organization_id,
    )

    if doi is None or not citation_entry.exists():
        # CitationEntrySerializer inherits from DefaultAuthenticatedSerializer,
        # which requires a request object with a user attached
        request = Request(HttpRequest())
        request.user = User.objects.get(id=user_id)

        json = generate_json_for_bibtex_entry(bibtex_entry)
        citation_type = BIBTEX_TO_CITATION_TYPES.get(
            bibtex_entry.entry_type, JOURNAL_ARTICLE
        )

        # see if we can find a paper with the same doi or url,
        # if so we can supplement the json with the paper's data
        related_unified_doc = None
        pdf = None
        try:
            paper = get_paper_by_doi(doi)
            paper_json = generate_json_for_rh_paper(paper)
            related_unified_doc = paper.unified_document.id
            if paper.file and pdf_copyright_allows_display(paper):
                pdf = paper.file
            json = merge_jsons(json, paper_json)
        except Paper.DoesNotExist:
            try:
                paper = get_paper_by_url(bibtex_entry.fields_dict.get("url", None))
                paper_json = generate_json_for_rh_paper(paper)
                related_unified_doc = paper.unified_document.id
                if paper.file and pdf_copyright_allows_display(paper):
                    pdf = paper.file
                json = merge_jsons(json, paper_json)
            except Paper.DoesNotExist:
                try:
                    paper = get_paper_by_doi_url(doi)
                    paper_json = generate_json_for_rh_paper(paper)
                    related_unified_doc = paper.unified_document.id
                    if paper.file and pdf_copyright_allows_display(paper):
                        pdf = paper.file
                    json = merge_jsons(json, paper_json)
                except Paper.DoesNotExist:
                    related_unified_doc = None
        except Exception as e:
            log_error(e)
            return None, False, "Unable to parse"

        # if we don't have a pdf, we want to try and get it from openalex.
        if pdf is None and doi is not None:
            open_alex = OpenAlex()
            oa_work = open_alex.get_data_from_doi(doi)
            if oa_work:
                loc = oa_work.get("best_oa_location", None) or oa_work.get(
                    "primary_location", None
                )
                if loc:
                    pdf_url = loc.get("pdf_url", None)
                if pdf_url is None:
                    loc = oa_work.get("open_access", {})
                    if loc:
                        pdf_url = loc.get("oa_url", None)

                if pdf_url:
                    pdf, _ = download_pdf(pdf_url)

        citation_entry_data = {
            "citation_type": citation_type,
            "fields": json,
            "created_by": user_id,
            "organization": organization_id,
            "project": project_id,
            "attachment": pdf,
            "doi": doi,
            "related_unified_doc": related_unified_doc,
        }

        try:
            context = {"request": request}
            serializer = CitationEntrySerializer(
                data=citation_entry_data, context=context
            )
            serializer.is_valid(raise_exception=True)
            entry = serializer.save()
            create_paper_from_citation(entry)

            error_msg = "" if pdf else "Unable to find PDF"
            return entry, False, error_msg
        except Exception as e:
            log_error(e)
            return None, False, "Unable to save"
    else:
        return citation_entry.first(), True, ""


def create_paper_from_citation(citation):
    doi = citation.doi

    if doi is None:
        return

    pure_doi = get_pure_doi(doi)

    try:
        duplicate_papers = get_paper_by_doi_url(doi)
    except Paper.DoesNotExist:
        duplicate_papers = None

    process_id = None

    if not duplicate_papers:
        data = {
            # We don't want the citation uploader to be considered the submitter
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

    return {"duplicate": duplicate_papers is not None, "process_id": process_id}


def get_paper_by_svf(key, query):
    search_query = SearchQuery(query)
    return Paper.objects.get(**{key: search_query})


def get_paper_by_doi(doi):
    return get_paper_by_svf("doi_svf", doi)


def get_paper_by_url(url):
    return get_paper_by_svf("url_svf", url) or get_paper_by_svf("pdf_url_svf", url)


def get_paper_by_doi_url(doi):
    # Appends http if protocol does not exist
    parsed_url = urlparse(doi)
    if not parsed_url.scheme:
        url = f"http://{parsed_url.geturl()}"
    else:
        url = doi

    return get_paper_by_url(url)
