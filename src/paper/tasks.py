from manubot.cite.doi import get_doi_csl_item

from hub.models import Hub
from paper.models import Paper
from paper.utils import get_pdf_from_url
from researchhub.celery import app
from utils.http import check_url_contains_pdf
from utils.semantic_scholar import SemanticScholar
from utils.crossref import Crossref


@app.task
def download_pdf(paper_id):
    paper = Paper.objects.get(id=paper_id)
    if paper.url and check_url_contains_pdf(paper.url):
        pdf = get_pdf_from_url(paper.url)
        filename = paper.url.split('/').pop()
        paper.file.save(filename, pdf)
        paper.save(update_fields=['file'])


@app.task
def add_references(paper_id):
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
    dois = [ref['doi'] for ref in reference_list]
    doi_set = set(dois)

    existing_papers = Paper.objects.filter(doi__in=doi_set)
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
        if semantic_paper:
            HUB_INSTANCE = 0
            hubs = [
                Hub.objects.get_or_create(name=hub_name.lower())[HUB_INSTANCE]
                for hub_name
                in semantic_paper.hub_candidates
            ]
            tagline = semantic_paper.abstract

        new_paper = None
        try:
            new_paper = create_manubot_paper(doi)
        except Exception:
            try:
                new_paper = create_crossref_paper(doi)
            except Exception:
                pass

        if new_paper:
            new_paper.hubs.add(*hubs)
            if reference_field == 'referenced_by':
                new_paper.references.add(paper)
            else:
                paper.references.add(new_paper)
            new_paper.save()

    paper.save()


def create_manubot_paper(doi):
    csl_item = get_doi_csl_item(doi)
    return Paper.create_from_csl_item(
        csl_item,
        doi=doi,
        externally_sourced=True,
        is_public=False
    )


def create_crossref_paper(doi):
    return Crossref(doi=doi).create_paper()
