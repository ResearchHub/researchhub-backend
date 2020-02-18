from paper.models import Paper
from paper.utils import download_pdf
from researchhub.celery import app

VALID_LICENSES = []


@app.task
def create_crossref_paper_with_csl(crossref_item):
    # csl_item = get_csl_item(crossref_item['URL'])  # This is very slow.
    # Paper.create_from_csl_item(csl_item)
    pass


@app.task
def get_authors_from_doi(authors):
    # for author in authors:
    # search orcid author
    #     query = author['given'] + ' ' + author['family']
    pass


@app.task
def download_pdf_by_license(item, paper_id):
    try:
        licenses = item['license']
        for license in licenses:
            if license in VALID_LICENSES:
                pdf, filename = get_pdf_and_filename(item['links'])
                paper = Paper.objects.get(pk=paper_id)
                paper.file.save(filename, pdf)
                paper.save(update_fields=['file'])
                break
    except Exception:
        pass


def get_pdf_and_filename(links):
    for link in links:
        if link['content-type'] == 'application/pdf':
            return download_pdf(link['URL'])
    return None, None
