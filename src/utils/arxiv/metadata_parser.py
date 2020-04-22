import gzip
import os
import shutil
import xmltodict

from hub.models import Hub
from paper.models import Paper
from utils.arxiv.categories import get_category_name


class ArxivRawMetadata:
    def __init__(
        self,
        abstract,
        arxiv_id,
        arxiv_url,
        authors,
        categories,
        category_names,
        doi,
        paper_date,
        title,
        url
    ):
        self.raw_abstract = abstract
        self.raw_arxiv_id = arxiv_id
        self.raw_arxiv_url = arxiv_url
        self.raw_authors = authors
        self.raw_categories = categories
        self.raw_category_names = category_names
        self.raw_doi = doi
        self.raw_paper_date = paper_date
        self.raw_title = title

        self.hubs = self._convert_categories_to_hubs()
        self.paper_publish_date = self._format_paper_publish_date()
        self.pdf_url = self._build_pdf_url()

    def create_paper(self):
        try:
            paper, created = Paper.objects.get_or_create(
                doi=self.raw_doi,
                defaults={
                    'abstract': self.raw_abstract,
                    'is_public': False,
                    'paper_publish_date': self.paper_publish_date,
                    'paper_title': self.raw_title,
                    'title': self.raw_title,
                    'pdf_url': self.pdf_url,
                    'raw_authors': self.raw_authors,
                    'retrieved_from_external_source': True,
                    'external_source': 'arxiv',
                    'url': self.raw_arxiv_url
                }
            )
            paper.hubs.add(*self.hubs)
        except Exception as e:
            # TODO: Sentry log
            print(e)

    def _build_pdf_url(self):
        return f'https://arxiv.org/pdf/{self.raw_arxiv_id}.pdf'

    def _convert_categories_to_hubs(self):
        hubs = []
        for category in self.raw_category_names:
            hub, created = Hub.objects.get_or_create(name=category.lower())
            hubs.append(hub)
        return hubs

    def _format_paper_publish_date(self):
        pass


def extract_arxiv_metadata(dir_name):
    count = 0
    for root, dirs, files in os.walk(dir_name):
        for file in files:
            if file.endswith('.xml.gz'):
                path = root + '/' + file
                xml_path = '.'.join(path.split('.')[:-1])

                if os.path.exists(xml_path):
                    print(
                        f'WARNING: Skipping {xml_path} . It already exists.'
                    )
                else:
                    with gzip.open(path, 'r') as f_in, open(xml_path, 'wb') as f_out:  # noqa
                        shutil.copyfileobj(f_in, f_out)
                    count += 1
                    print(xml_path)
    print(f'Done. Extracted files from {dir_name}: {count}')


def parse_arxiv_metadata(path_to_file):
    records = []

    with open(path_to_file) as file:
        doc = xmltodict.parse(file.read())
        for record in doc['Response']['ListRecords']['record']:
            metadata = record['metadata']['arXivRaw']

            abstract = metadata['abstract']
            arxiv_id = metadata['id']
            authors = metadata['authors']
            categories = metadata['categories']
            category_names = [
                get_category_name(category) for category in categories
            ]
            doi = None
            try:
                doi = metadata['doi']
            except KeyError:
                pass
            paper_date = None
            try:
                paper_date = metadata['version'][0]['date']
            except KeyError:
                try:
                    paper_date = metadata['version']['date']
                except Exception:
                    pass
            title = metadata['title']

            parsed = ArxivRawMetadata(
                abstract=abstract,
                arxiv_id=arxiv_id,
                authors=authors,
                categories=categories,
                category_names=category_names,
                doi=doi,
                paper_date=paper_date,
                title=title
            )
            records.append(parsed)
    return records
