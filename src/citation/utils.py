import pdf2doi

from citation.models import CitationEntry
from citation.constants import CITATION_TYPE_FIELDS, JOURNAL_ARTICLE
from citation.schema import generate_json_for_journal

def get_citation_entry_from_pdf(pdf, user_id, organization_id, project_id):
    conversion = pdf2doi.pdf2doi_singlefile(pdf)
    json = generate_json_for_journal(conversion)
    entry = CitationEntry.objects.create(
        citation_type=JOURNAL_ARTICLE,
        fields=json,
        created_by_id=user_id,
        organization_id=organization_id,
        attachment=pdf,
        doi=json['DOI'],
        project_id=project_id
    )
    return entry
