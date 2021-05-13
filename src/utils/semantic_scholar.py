import logging
import time

from django.apps import apps

from utils.http import GET, http_request


class SemanticScholar:
    """A paper in \"citations\" lists the current doi in its references section.
    A paper in \"references\" is listed in the references section of the
    current doi.
    """

    base_url = 'https://api.semanticscholar.org/v1/paper/'
    ID_TYPES = {
        'doi': 'doi',
        'arxiv': 'arXiv',
    }

    def __init__(self, id, id_type='doi'):
        assert id is not None, '`id` must not be `None`'
        self.id = id
        self.id_type = id_type
        self.response = None
        self.data = None
        self.references = []
        self.referenced_by = []
        self.hub_candidates = []
        self.abstract = None
        self.execute(self.id)

    def execute(self, id):
        url = self.base_url
        if id is not None:
            if (
                (self.id_type == self.ID_TYPES['arxiv'])
                and (not id.startswith('arXiv:'))
            ):
                url += f'arXiv:{id}'
            else:
                url += id

        status_code = None
        try:
            response = self._get_response(url)
            status_code = response.status_code
            self.response = response
            self.data = self.response.json()

            self.doi = None
            doi = self.data.get('doi', None)
            if (doi is None) and (self.id_type == self.ID_TYPES['doi']):
                self.doi = self.id

            self.alternate_ids = {}
            self.arxiv_id = None
            arxiv_id = self.data.get('arxivId', None)
            if arxiv_id is not None:
                if not arxiv_id.startswith('arXiv:'):
                    arxiv_id = f'arXiv:{arxiv_id}'
                self.arxiv_id = arxiv_id
            elif (arxiv_id is None) and (
                self.id_type == self.ID_TYPES['arxiv']
            ):
                self.arxiv_id = self.id
            if self.arxiv_id is not None:
                self.alternate_ids = {'arxiv': self.arxiv_id}

            self.abstract = self.data.get('abstract', None)
            self.hub_candidates = self.data.get('fieldsOfStudy', [])
            self.title = self.data.get('title', None)
            authors = self.data.get('authors', None)
            self.raw_authors = self._construct_authors(authors)
            self.references = self.data.get('references', [])
            self.referenced_by = self.data.get('citations', [])
            self.year = self.data.get('year', None)
        except Exception as e:
            print(e)

        if status_code == 403:
            raise UserWarning(
                '''Semantic scholar is returning 403.
                Try this operation again later.'''
            )

    def create_paper(self, is_public=False):
        Paper = apps.get_model('paper.Paper')
        if (self.data is not None) and (self.id is not None):
            paper = Paper.objects.create(
                abstract=self.abstract,
                title=self.title,
                paper_title=self.title,
                doi=self.doi,
                alternate_ids=self.alternate_ids,
                external_source='semantic_scholar',
                raw_authors=self.raw_authors,
                retrieved_from_external_source=True,
                is_public=is_public
            )
            return paper
        return None

    def _get_response(self, url):
        response = http_request(GET, url)
        time.sleep(.1)

        if response.status_code == 429:
            logging.warning(
                'Semantic Scholar responded with 429. Sleeping for 4 seconds'
            )
            time.sleep(4)
            response = http_request(GET, url)

        if response.status_code == 403:
            logging.warning(
                'Semantic Scholar responded with 403. Sleeping for 5 minutes'
            )
            time.sleep(300)
            response = http_request(GET, url)

        return response

    def _construct_authors(self, authors):
        if authors is None:
            return
        # TODO: Unclear how reliable this parsing is because we get authors as
        # a single string from Semantic Scholar. E.g. not sure if they include
        # middle names.
        raw_authors = []
        for author in authors:
            try:
                name_parts = author['name'].split(' ', 1)
                raw_authors.append({
                    'first_name': name_parts[0],
                    'last_name': name_parts[1]
                })
            except Exception as e:
                print(f'Failed to construct author: {author}', e)
        return raw_authors
