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
    'zoology'
]

HUBS = [
    Hub.objects.get_or_create(name=category.lower())[0]
    for category in CATEGORIES
]


class Command(BaseCommand):

    def handle(self, *args, **options):
        base_url = 'https://api.rxivist.org/v1/papers?metric=downloads&'
        meta_data = requests.get(base_url).json()['query']
        preprint_count = meta_data['total_results']
        preprint_pages = meta_data['final_page']
        print(f'Total amount of preprints: {preprint_count}')
        for i in range(preprint_pages):
            print(f'{i}/{preprint_pages}')
            url = base_url + f'page_size=250&page={i}'
            response = requests.get(url)
            if response.status_code != 200:
                print(f'ERROR: {response.text}')
                break

            results = response.json()['results']
            for res in results:
                self.create_paper(res)

            if i > 5:
                break

    def construct_authors(self, authors):
        # return [{'first_name': author['name'].split(' ')[0], 'last_name': author['name'].split(' ')[-1]} for author in authors]
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

    def create_paper(self, data):
        doi = data.get('doi')
        abstract = data.get('abstract')
        publish_date = data.get('first_posted')
        title = data.get('title')
        url = data.get('biorxiv_url')
        pdf_url = url + '.full.pdf'
        authors = self.construct_authors(data.get('authors'))
        external_source = 'biorxiv'
        paper = None

        # TODO: Add in logic for downloading the pdf?
        # pdf_request = requests.get(pdf_url)
        # if pdf_request.status_code == 200:
        #     pass
        # else:
        #     pdf_url = None

        query = Q(url=url) | Q(pdf_url=pdf_url)
        if doi is not None:
            query = query | Q(doi=doi)

        paper_results = Paper.objects.filter(query)
        if len(paper_results) > 0:
            paper = paper_results[0]
        else:
            try:
                paper = Paper.objects.create(
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
            except Exception as e:
                print(e)
        if paper is not None:
            paper.hubs.add(*HUBS)
        else:
            print('No paper for biorxiv id', data.get('id'))
