from urllib.parse import urlparse

import requests
from django.contrib.postgres.search import SearchQuery
from django.db.models import Q

from citation.constants import JOURNAL_ARTICLE
from citation.exceptions import GrobidProcessingError
from citation.models import CitationEntry
from citation.schema import generate_json_for_journal
from citation.serializers import CitationEntrySerializer
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers import PaperSubmissionSerializer
from researchhub.settings import AWS_STORAGE_BUCKET_NAME, GROBID_SERVER
from utils.sentry import log_error


def get_pdf_header_data(path):
    url = f"{GROBID_SERVER}/header_extract"
    request_data = {
        "s3_file_path": f"{path}",
        "bucket_name": f"{AWS_STORAGE_BUCKET_NAME}",
    }
    try:
        response = request_data.post(url, data=request_data, timeout=10)
        data = response.json()
        status = data.get("status")
        if status == 200:
            return response.json()
    except requests.ConnectionError as e:
        log_error(e)
        raise GrobidProcessingError(e, "Grobid server timed out")

    raise GrobidProcessingError(
        "Could not extract data", "Grobid queue is most likely full"
    )


def get_citation_entry_from_pdf(path, user_id, organization_id, project_id):
    header_data = get_pdf_header_data(path)
    doi = header_data.get("doi")
    json = generate_json_for_journal(doi)
    citation_entry = CitationEntry.objects.filter(
        doi=json["DOI"], created_by_id=user_id, project_id=project_id
    )
    if not citation_entry.exists():
        citation_entry_data = {
            "citation_type": JOURNAL_ARTICLE,
            "fields": json,
            "created_by": user_id,
            "organization": organization_id,
            "attachment": path,
            "doi": doi,
            "project": project_id,
        }
        serializer = CitationEntrySerializer(data=citation_entry_data)
        serializer.is_valid(raise_exception=True)
        entry = serializer.save()
        create_paper_from_citation(entry)
        return entry, False
    else:
        return citation_entry.first(), True


def create_paper_from_citation(citation):
    url = citation.doi

    # Appends http if protocol does not exist
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        url = f"http://{parsed_url.geturl()}"

    duplicate_papers = Paper.objects.filter(
        Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(url))
    )

    process_id = None

    if not duplicate_papers:
        data = {"uploaded_by": citation.created_by.id, "url": url}
        submission = PaperSubmissionSerializer(data=data)
        if submission.is_valid():
            submission = submission.save()
            process_id = celery_process_paper(submission.id)
    else:
        print("duplicate paper with doi {}".format(citation.doi))

    return {"duplicate": duplicate_papers.exists(), "process_id": process_id}
