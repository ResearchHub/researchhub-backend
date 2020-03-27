from manubot.cite.doi import get_doi_csl_item

from utils.semantic_scholar import SemanticScholar
from utils.crossref import Crossref

import fitz
import os
import requests
import shutil
from subprocess import call

from django.apps import apps
from django.core.files import File

from researchhub.celery import app
from paper.utils import (
    get_pdf_from_url,
    get_crossref_results,
    fitz_extract_figures
)
from utils.http import check_url_contains_pdf


@app.task
def download_pdf(paper_id):
    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    if paper.url and check_url_contains_pdf(paper.url):
        pdf = get_pdf_from_url(paper.url)
        filename = paper.url.split('/').pop()
        paper.file.save(filename, pdf)
        paper.save(update_fields=['file'])


@app.task
def add_references(paper_id):
    Paper = apps.get_model('paper.Paper')
    paper = Paper.objects.get(id=paper_id)
    if paper.doi:
        semantic_paper = SemanticScholar(paper.doi)
        references = semantic_paper.references
        referenced_by = semantic_paper.referenced_by

        if paper.references.count() < 1:
            add_or_create_reference_papers(paper, references, 'references')

        if paper.referenced_by.count() < 1:
            add_or_create_reference_papers(
                paper,
                referenced_by,
                'referenced_by'
            )


def add_or_create_reference_papers(paper, reference_list, reference_field):
    Paper = apps.get_model('paper.Paper')
    Hub = apps.get_model('hub.Hub')
    dois = [ref['doi'] for ref in reference_list]
    doi_set = set(dois)

    existing_papers = Paper.objects.filter(doi__in=dois)
    for existing_paper in existing_papers:
        if reference_field == 'referenced_by':
            existing_paper.references.add(paper)
        else:
            paper.references.add(existing_paper)

    doi_hits = set(existing_papers.values_list('doi', flat=True))
    doi_misses = doi_set.difference(doi_hits)

    for doi in doi_misses:
        if not doi:
            continue
        hubs = []
        tagline = None
        semantic_paper = SemanticScholar(doi)
        if semantic_paper is not None:
            if semantic_paper.hub_candidates is not None:
                HUB_INSTANCE = 0
                hubs = [
                    Hub.objects.get_or_create(
                        name=hub_name.lower()
                    )[HUB_INSTANCE]
                    for hub_name
                    in semantic_paper.hub_candidates
                ]
            tagline = semantic_paper.abstract

        new_paper = None
        try:
            new_paper = create_manubot_paper(doi)
        except Exception as e:
            print(f'Error creating manubot paper: {e}')
            try:
                new_paper = create_crossref_paper(doi)
            except Exception as e:
                print(f'Error creating crossref paper: {e}')
                pass

        if new_paper is not None:
            if not new_paper.tagline:
                new_paper.tagline = tagline
            new_paper.hubs.add(*hubs)
            if reference_field == 'referenced_by':
                new_paper.references.add(paper)
            else:
                paper.references.add(new_paper)
            try:
                new_paper.save()
            except Exception as e:
                print(f'Error saving reference paper: {e}')

    paper.save()


def create_manubot_paper(doi):
    Paper = apps.get_model('paper.Paper')

    csl_item = get_doi_csl_item(doi)
    return Paper.create_from_csl_item(
        csl_item,
        doi=doi,
        externally_sourced=True,
        is_public=False
    )


def create_crossref_paper(doi):
    return Crossref(doi=doi).create_paper()


@app.task
def celery_extract_figures(paper_id):
    Paper = apps.get_model('paper.Paper')
    Figure = apps.get_model('paper.Figure')
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return

    path = f'/tmp/figures/{paper_id}/'
    filename = f'{paper.id}.pdf'
    file_path = f'{path}{filename}'
    file_url = file.url

    if not os.path.isdir(path):
        os.mkdir(path)

    res = requests.get(file_url)
    with open(file_path, 'wb+') as f:
        f.write(res.content)

    fitz_extract_figures(file_path)

    figures = os.listdir(path)
    if len(figures) == 1:  # Only the pdf exists
        args = [
            'java',
            '-jar',
            'pdffigures2-assembly-0.1.0.jar',
            file_path,
            '-m',
            path,
            '-d',
            path,
            '-e'
        ]
        call(args)
        figures = os.listdir(path)

    for extracted_figure in figures:
        extracted_figure_path = f'{path}{extracted_figure}'
        if '.png' in extracted_figure:
            with open(extracted_figure_path, 'rb') as f:
                extracted_figures = Figure.objects.filter(paper=paper)
                if not extracted_figures.filter(
                    file__contains=f.name,
                    figure_type=Figure.FIGURE
                ):
                    Figure.objects.create(
                        file=File(f),
                        paper=paper,
                        figure_type=Figure.FIGURE
                    )
    shutil.rmtree(path)


@app.task
def celery_extract_pdf_preview(paper_id):
    Paper = apps.get_model('paper.Paper')
    Figure = apps.get_model('paper.Figure')
    paper = Paper.objects.get(id=paper_id)

    file = paper.file
    if not file:
        return

    path = f'/tmp/figures/preview-{paper_id}/'
    filename = f'{paper.id}.pdf'
    file_path = f'{path}{filename}'
    file_url = file.url

    if not os.path.isdir(path):
        os.mkdir(path)

    res = requests.get(file_url)
    with open(file_path, 'wb+') as f:
        f.write(res.content)

    doc = fitz.open(file_path)
    extracted_figures = Figure.objects.filter(paper=paper)
    for page in doc:
        pix = page.getPixmap(alpha=False)
        output_filename = f'{file_path}-{page.number}.png'
        pix.writePNG(output_filename)

        if not extracted_figures.filter(
            file__contains=output_filename,
            figure_type=Figure.PREVIEW
        ):
            with open(output_filename, 'rb') as f:
                Figure.objects.create(
                    file=File(f),
                    paper=paper,
                    figure_type=Figure.PREVIEW
                )

    shutil.rmtree(path)


@app.task
def celery_extract_meta_data(title):
    results = get_crossref_results(title)
