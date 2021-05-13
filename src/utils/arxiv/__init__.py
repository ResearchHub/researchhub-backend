import arxiv
from django.apps import apps

from hub.models import Hub
from utils.arxiv.categories import get_category_name

HUB_INSTANCE = 0


class Arxiv:
    def __init__(self, id=None, query=None, title=None):
        # TODO: Handle query case
        self.id = id
        self.data = None
        self._handle_doi(self.id)
        self.editorialized_title = title

    def _handle_doi(self, id):
        id = id.replace('arXiv:', '')
        self.data = arxiv.query(id_list=[id])
        if type(self.data) is list:
            self.data = self.data[0]

        if self.data is not None:
            self.abstract = self.data.get('summary')
            self.arxiv_id = self.id
            self.alternate_ids = {'arxiv': self.arxiv_id}
            self.authors = self.data.get('authors', [])
            self.raw_authors = self.construct_authors(self.authors)
            self.doi = self.data.get('doi')
            self.title = self.data.get('title')
            self.paper_publish_date = self._parse_published()
            self.pdf_url = self.data.get('pdf_url')
            self.url = self.data.get('arxiv_url')

    def create_paper(self, public=True, uploaded_by=None):
        Paper = apps.get_model('paper.Paper')

        external = True
        external_source = 'arxiv'
        if uploaded_by is not None:
            external = False
            external_source = None

        if (self.data is not None) and (self.id is not None):
            self.paper = Paper.objects.create(
                abstract=self.abstract,
                title=self.editorialized_title or self.title,
                paper_title=self.title,
                doi=self.doi,
                alternate_ids=self.alternate_ids,
                external_source=external_source,
                paper_publish_date=self.paper_publish_date,
                pdf_url=self.pdf_url,
                raw_authors=self.raw_authors,
                retrieved_from_external_source=external,
                is_public=public,
                uploaded_by=uploaded_by,
                url=self.url,
            )
            return self.paper
        return None

    def add_hubs(self, hubs=[]):
        if len(hubs) < 1:
            hubs = self._get_hubs()
        self.paper.hubs.add(*hubs)

    def construct_authors(self, authors):
        raw_authors = []
        for author in authors:
            name_parts = author.split(' ', 1)
            if len(name_parts) == 2:
                raw_authors.append({
                    'first_name': name_parts[0],
                    'last_name': name_parts[1]
                })
        return raw_authors

    def _get_hubs(self):
        category = self.data.get('arxiv_primary_category')
        if category is not None:
            term = category.get('term')
            category_name = get_category_name(term)
            return [
                Hub.objects.get_or_create(
                    name=category_name.lower()
                )[HUB_INSTANCE]
            ]

    def _parse_published(self):
        published = self.data.get('published')
        if published is not None:
            parts = published.split('T')
            return parts[0]
        return None
