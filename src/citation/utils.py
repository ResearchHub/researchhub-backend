import pdf2doi

from citation.constants import CITATION_TYPE_FIELDS, JOURNAL_ARTICLE
from citation.schema import generate_json_for_journal
from citation.serializers import CitationEntrySerializer


def get_citation_entry_from_pdf(pdf, user_id, organization_id, project_id):
    conversion = pdf2doi.pdf2doi_singlefile(pdf)
    json = generate_json_for_journal(conversion)
    data = {
        "citation_type": JOURNAL_ARTICLE,
        "fields": json,
        "created_by_id": user_id,
        "organization_id": organization_id,
        "attachment": pdf,
        "doi": json["DOI"],
        "project_id": project_id,
    }
    serializer = CitationEntrySerializer(data=data)
    serializer.is_valid(raise_exception=True)
    entry = serializer.save()
    return entry
