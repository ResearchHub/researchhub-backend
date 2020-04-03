import logging
from django.apps import apps
from django.utils import timezone
import habanero


class Crossref:
    def __init__(self, doi=None, query=None):
        # TODO: Handle query case
        self.cr = habanero.Crossref()
        self.data = None
        self.data_message = None
        self.reference_count = None
        self.referenced_by_count = None
        self.referenced_by = []
        self.references = []
        if doi:
            self.handle_doi(doi)

    def handle_doi(self, doi):
        try:
            self.doi = doi
            self.data = self.cr.works(ids=[doi])
            self.data_message = self.data['message']
        except Exception as e:
            self.data_message = None
            logging.warning(e)
        else:
            self.reference_count = self.data_message.get(
                'reference-count',
                None
            )
            self.referenced_by_count = self.data_message.get(
                'is-referenced-by-count',
                None
            )
            if self.reference_count > 0:
                try:
                    self.references = self.data_message.get('reference', [])
                except Exception as e:
                    logging.warning(
                        f'Reference count > 0 but found error: {e}'
                    )
            if self.referenced_by_count > 0:
                try:
                    relation = self.data_message.get('relation', None)
                    if relation is not None:
                        self.referenced_by = relation.get('cites', [])
                except Exception as e:
                    logging.warning(
                        f'Referenced by count > 0 but found error: {e}'
                    )

    def create_paper(self):
        Paper = apps.get_model('paper.Paper')
        if self.data_message is not None:
            item = self.data_message
            item_type = item.get('type', None)
            if item_type == 'journal-article':
                doi = item.get('DOI', None)
                if doi is not None:
                    title = item.get('title', [])[0]
                    url = item.get('URL', None)
                    paper = Paper.objects.create(
                        title=title,
                        paper_title=title,
                        doi=doi,
                        url=url,
                        paper_publish_date=get_crossref_issued_date(item),
                        external_source='crossref',
                        retrieved_from_external_source=True,
                        is_public=False
                    )
                    return paper
        return None


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
