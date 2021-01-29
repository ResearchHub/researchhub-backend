import gzip
import os
import shutil
import xmltodict

from django.db.models import Q
from django.utils import timezone

from hub.models import Hub
from paper.models import Paper
from utils.arxiv.categories import get_category_name


class ArxivMetadata:
    def __init__(
        self,
        abstract,
        arxiv_id,
        authors,
        categories,
        category_names,
        doi,
        date,
        title,
    ):
        self.raw_abstract = abstract
        self.raw_arxiv_id = arxiv_id
        self.raw_authors = authors
        self.raw_categories = categories
        self.raw_category_names = category_names
        self.raw_doi = doi
        self.raw_date = date
        self.raw_title = title

        self.arxiv_url = self._build_arxiv_url()
        self.hubs = self._convert_categories_to_hubs()
        self.pdf_url = self._build_pdf_url()

    def create_paper(self):
        paper = None
        query = Q(url=self.arxiv_url) | Q(pdf_url=self.pdf_url)
        if self.raw_doi is not None:
            query = query | Q(doi=self.raw_doi)
        paper_results = Paper.objects.filter(query)
        if len(paper_results) > 0:
            paper = paper_results[0]
        else:
            try:
                paper = Paper.objects.create(
                    doi=self.raw_doi,
                    abstract=self.raw_abstract,
                    is_public=True,
                    paper_publish_date=self.raw_date,
                    paper_title=self.raw_title,
                    title=self.raw_title,
                    pdf_url=self.pdf_url,
                    raw_authors=self.raw_authors,
                    retrieved_from_external_source=True,
                    external_source='arxiv',
                    url=self.arxiv_url
                )
            except Exception as e:
                print(e)
        if paper is not None:
            paper.hubs.add(*self.hubs)
        else:
            print('No paper for arxiv id', self.raw_arxiv_id)

    def _build_arxiv_url(self):
        return f'https://arxiv.org/abs/{self.raw_arxiv_id}'

    def _build_pdf_url(self):
        return f'https://arxiv.org/pdf/{self.raw_arxiv_id}.pdf'

    def _convert_categories_to_hubs(self):
        hubs = []
        for category in self.raw_category_names:
            hub, created = Hub.objects.get_or_create(name=category.lower())
            hubs.append(hub)
        return hubs


def extract_from_directory(dir_name):
    xml_files = []
    extracted_count = 0
    for root, dirs, files in os.walk(dir_name):
        for file in files:
            if file.endswith('.xml.gz'):
                xml_path, did_extract = extract_xml_gzip(root + '/' + file)
                if xml_path is not None:
                    xml_files.append(xml_path)
                    if did_extract:
                        extracted_count += 1
    print(f'Extracted {extracted_count} files. Returned {len(xml_files)}')
    return xml_files


def extract_xml_gzip(file):
    print('Extracting file', file)
    did_extract = False
    xml_path = '.'.join(file.split('.')[:-1])
    if os.path.exists(xml_path):
        print(
            f'WARNING: Skipping {xml_path} . It already exists.'
        )
    else:
        try:
            with gzip.open(file, 'r') as f_in, open(xml_path, 'wb') as f_out:  # noqa
                shutil.copyfileobj(f_in, f_out)
            did_extract = True
        except OSError as e:
            print('Failed to open:', e)
    return xml_path, did_extract


def parse_arxiv_metadata(path_to_file):
    records = []

    with open(path_to_file) as file:
        try:
            doc = xmltodict.parse(file.read())
            for record in doc['Response']['ListRecords']['record']:
                parsed = None
                try:
                    metadata = record['metadata']['arXivRaw']
                    parsed = parse_arXivRaw_format(metadata)
                except KeyError:
                    metadata = record['metadata']['arXiv']
                    parsed = parse_arXiv_format(metadata)
                records.append(parsed)
        except Exception as e:
            print(path_to_file, e)
    return records


def parse_arXiv_format(metadata):
    abstract = metadata['abstract']
    arxiv_id = metadata['id']
    author_metadata = metadata['authors']['author']
    authors = []
    if type(author_metadata) is list:
        for author in author_metadata:
            authors.append(construct_author(author))
    else:
        authors.append(construct_author(author_metadata))
    categories = metadata['categories'].split(' ')
    category_names = [
        get_category_name(category) for category in categories
    ]
    doi = None
    try:
        doi = metadata['doi']
    except KeyError:
        pass
    paper_date = metadata['created']
    title = metadata['title']

    parsed = ArxivMetadata(
        abstract=abstract,
        arxiv_id=arxiv_id,
        authors=authors,
        categories=categories,
        category_names=category_names,
        doi=doi,
        date=paper_date,
        title=title
    )
    return parsed


def construct_author(author):
    first_name = None
    last_name = None
    try:
        first_name = author['forenames']
    except KeyError:
        pass
    try:
        last_name = author['keyname']
    except KeyError:
        pass
    return {'first_name': first_name, 'last_name': last_name}


def parse_arXivRaw_format(metadata):
    abstract = metadata['abstract']
    arxiv_id = metadata['id']
    authors = metadata['authors'].split(', ')
    categories = metadata['categories'].split(' ')
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
    if paper_date is not None:
        paper_date = timezone.datetime.strptime(
            paper_date,
            '%a, %d %b %Y %X %Z'
        )

    title = metadata['title']

    parsed = ArxivMetadata(
        abstract=abstract,
        arxiv_id=arxiv_id,
        authors=authors,
        categories=categories,
        category_names=category_names,
        doi=doi,
        date=paper_date,
        title=title
    )
    return parsed
