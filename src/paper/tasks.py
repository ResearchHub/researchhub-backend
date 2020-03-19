from manubot.cite.doi import get_doi_csl_item

from researchhub.celery import app
from paper.models import Paper
from paper.utils import check_url_contains_pdf, get_pdf_from_url
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
    dois = set()
    for ref in reference_list:
        dois.add(ref['doi'])
    rh_papers = Paper.objects.filter(doi__in=dois)
    getattr(paper, reference_field).add(*rh_papers)

    doi_hits = set(rh_papers.values_list('doi', flat=True))
    doi_misses = dois.difference(doi_hits)

    new_papers = []
    for doi in doi_misses:
        try:
            csl_item = get_doi_csl_item(doi)
            manubot_paper = Paper.create_from_csl_item(csl_item)
            new_papers.append(manubot_paper)
        except Exception as e:
            print(e)
            try:
                crossref_paper = Crossref(doi=doi).create_paper()
                new_papers.append(crossref_paper)
            except Exception as e:
                print(e)

    getattr(paper, reference_field).add(*new_papers)
