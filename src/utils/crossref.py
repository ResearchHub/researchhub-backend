import logging
import re

from django.apps import apps
from django.utils import timezone
import habanero


class Crossref:
    def __init__(self, id=None, query=None):
        # TODO: Handle query case
        self.cr = habanero.Crossref(mailto='dev@quantfive.org')

        self.data = None
        self.data_message = None

        self.abstract = None
        self.id = id
        self.reference_count = None
        self.referenced_by_count = None
        self.referenced_by = []
        self.references = []
        self.title = None

        if self.id is not None:
            self.handle_id()

    def handle_id(self):
        try:
            self.data = self.cr.works(ids=[self.id])
            self.data_message = self.data['message']
        except Exception as e:
            self.data_message = None
            logging.warning(e)
        else:
            self.abstract = self.data_message.get('abstract', None)

            # Remove any jat xml tags
            if self.abstract is not None:
                self.abstract = re.sub(r'<[^<]+>', '', self.abstract)

            self.doi = self.data_message.get('DOI', None)
            self.arxiv_id = self.data_message.get('arxiv', None)

            self.paper_publish_date = get_crossref_issued_date(
                self.data_message
            )

            self.publication_type = self.data_message.get('type', None)

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

            self.title = None
            title = self.data_message.get('title', [None])
            if (type(title) is list):
                if (len(title) > 0):
                    self.title = title[0]
            elif type(title) is str and (title != ''):
                self.title = title
            if self.title is None:
                logging.warning('Crossref did not find title')

            self.url = self.data_message.get('URL', None)

    def create_paper(self, is_public=False):
        Paper = apps.get_model('paper.Paper')
        if self.data_message is not None:
            if self.publication_type == 'journal-article':
                if self.id is not None:
                    paper = Paper.objects.create(
                        title=self.title,
                        paper_title=self.title,
                        doi=self.doi,
                        alternate_ids={'arxiv': self.arxiv_id},
                        url=self.url,
                        paper_publish_date=self.paper_publish_date,
                        publication_type=self.publication_type,
                        external_source='crossref',
                        retrieved_from_external_source=True,
                        is_public=is_public
                    )
                    return paper
        return None


def get_crossref_issued_date(item):
    parts = item['issued']['date-parts'][0]
    day = 1
    month = 1
    year = None
    if len(parts) > 2:
        day = parts[2] or day
    if len(parts) > 1:
        month = parts[1] or month
    if len(parts) > 0:
        year = parts[0]
    if year is not None:
        return timezone.datetime(year, month, day)
    else:
        return None
