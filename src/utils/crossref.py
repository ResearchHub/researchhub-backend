from django.utils import timezone
import habanero

from paper.models import Paper


class Crossref:
    def __init__(self, doi=None, query=None):
        self.cr = habanero.Crossref()
        if doi:
            self.handle_doi(doi)
        # TODO: Handle query case

    def handle_doi(self, doi):
        self.doi = doi
        self.data = self.cr.works(ids=[doi])
        self.reference_count = self.data['message']['reference-count']
        self.referenced_by_count = (
            self.data['message']['is-referenced-by-count']
        )
        # TODO: Check if keys exist when count is 0
        if self.reference_count > 0:
            self.references = self.data['message']['reference']
        if self.referenced_by_count > 0:
            self.referenced_by = self.data['message']['relation']['cites']

    def create_paper(self):
        item = self.data['message']
        paper = Paper.objects.create(
            title=item['title'][0],
            paper_title=item['title'][0],
            doi=item['DOI'],
            url=item['URL'],
            paper_publish_date=get_crossref_issued_date(item),
            retrieved_from_external_source=True,
            is_public=False
        )
        # download_pdf_by_license.signature((item, paper.id))
        return paper


def get_crossref_issued_date(item):
    parts = item['issued']['date-parts'][0]
    day = 1
    month = 1
    if len(parts) > 2:
        day = parts[2]
    if len(parts) > 1:
        month = parts[1]
    if len(parts) > 0:
        year = parts[0]
        return timezone.datetime(year, month, day)
