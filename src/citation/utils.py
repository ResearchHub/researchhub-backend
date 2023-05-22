import pdf2doi

from citation.constants import CITATION_TYPE_FIELDS, JOURNAL_ARTICLE
from citation.models import CitationEntry
from citation.schema import generate_json_for_journal
from paper.models import Paper
from paper.paper_upload_tasks import celery_process_paper
from paper.serializers import PaperSubmissionSerializer


def get_citation_entry_from_pdf(pdf, user_id, organization_id, project_id):
    conversion = pdf2doi.pdf2doi_singlefile(pdf)
    json = generate_json_for_journal(conversion)
    entry = CitationEntry.objects.create(
        citation_type=JOURNAL_ARTICLE,
        fields=json,
        created_by_id=user_id,
        organization_id=organization_id,
        attachment=pdf,
        doi=json["DOI"],
        project_id=project_id,
    )
    create_paper_from_citation(entry)
    return entry


def create_paper_from_citation(citation):
    url = citation.doi

    # Appends http if protocol does not exist
    parsed_url = urlparse(url)
    if not parsed_url.scheme:
        url = f"http://{parsed_url.geturl()}"
        data["url"] = url

    duplicate_papers = Paper.objects.filter(
        Q(url_svf=SearchQuery(url)) | Q(pdf_url_svf=SearchQuery(url))
    )

    process_id = None

    if not duplicate_papers:
        submission = PaperSubmissionSerializer.create(
            uploaded_by=citation.created_by, url=url
        )
        process_id = celery_process_paper(submission.id)

    return {"duplicate": duplicate_papers.exists(), "process_id": process_id}
