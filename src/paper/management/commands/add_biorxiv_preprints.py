'''
Adding preprints from biorxiv
'''

import requests

from django.db.models import Q
from django.core.management.base import BaseCommand

from hub.models import Hub
from paper.models import Paper

CATEGORIES = [
    'animal-behavior-and-cognition',
    'biochemistry',
    'bioengineering',
    'bioinformatics',
    'biophysics',
    'cancer-biology',
    'cell-biology',
    'clinical-trials',
    'developmental-biology',
    'ecology',
    'epidemiology',
    'evolutionary-biology',
    'genetics',
    'genomics',
    'immunology',
    'microbiology',
    'molecular-biology',
    'neuroscience',
    'paleontology',
    'pathology',
    'pharmacology-and-toxicology',
    'physiology',
    'plant-biology',
    'scientific-communication-and-education',
    'synthetic-biology',
    'systems-biology',
    'zoology',
    'other'
]


class Command(BaseCommand):

    def __init__(self, *args, **kwargs):
        HUBS = [
            Hub.objects.get_or_create(name=category)[0]
            for category in CATEGORIES
        ]
        self.HUBS = HUBS
        super().__init__(*args, **kwargs)

    def handle(self, *args, **options):
        base_url = 'https://api.rxivist.org/v1/papers?metric=downloads&page_size=250'
        meta_data = requests.get(base_url).json()['query']
        preprint_count = meta_data['total_results']
        preprint_pages = meta_data['final_page']
        print(f'Total amount of preprints: {preprint_count}')
        for i in range(preprint_pages):
            print(f'{i}/{preprint_pages}')
            url = base_url + f'&page={i}'
            response = requests.get(url)
            if response.status_code != 200:
                print(f'ERROR: {response.text}')
                break

            results = response.json()['results']
            self.create_papers(results)

    def construct_authors(self, authors):
        authors_list = []
        for author in authors:
            name = author['name'].split(' ')
            first_name = name[0]
            last_name = name[-1]
            authors_list.append(
                {
                    'first_name': first_name,
                    'last_name': last_name
                }
            )
        return authors_list

    def create_papers(self, results):
        papers = []
        hub_ids = []
        for data in results:
            doi = data.get('doi')
            abstract = data.get('abstract')
            publish_date = data.get('first_posted')
            title = data.get('title')
            url = data.get('biorxiv_url')
            pdf_url = url + '.full.pdf' if url else None
            authors = self.construct_authors(data.get('authors'))
            external_source = 'biorxiv'
            category = data.get('category')
            paper = None

            if category == 'unknown':
                category = 'other'

            paper_hub = Hub.objects.get(name=category)

            query = Q(url=url) | Q(pdf_url=pdf_url) | Q(paper_title=title)
            if doi is not None:
                query = query | Q(doi=doi)

            paper_results = Paper.objects.filter(query)
            if len(paper_results) > 0:
                paper = paper_results[0]
                paper.hubs.add(paper_hub)
            else:
                try:
                    paper = Paper(
                        doi=doi,
                        abstract=abstract,
                        is_public=True,
                        paper_publish_date=publish_date,
                        paper_title=title,
                        title=title,
                        pdf_url=pdf_url,
                        raw_authors=authors,
                        retrieved_from_external_source=True,
                        external_source=external_source,
                        url=url
                    )
                    papers.append(paper)
                    hub_ids.append(paper_hub.id)
                except Exception as e:
                    print(e)

        hub_tags = []
        created_papers = Paper.objects.bulk_create(papers)
        paper_ids = list(map(lambda p: p.id, created_papers))
        for paper_id, hub_id in zip(paper_ids, hub_ids):
            hub_tag = Paper.hubs.through(paper_id=paper_id, hub_id=hub_id)
            hub_tags.append(hub_tag)
        Paper.hubs.through.objects.bulk_create(hub_tags)
