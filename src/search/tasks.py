from oauth.utils import get_orcid_works, check_doi_in_works
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


@app.task
def create_authors_from_crossref(crossref_authors, paper_doi):
    for crossref_author in crossref_authors:
        first_name = crossref_author['given']
        last_name = crossref_author['family']

        affiliation = None
        if len(crossref_author['affiliation']) > 0:
            FIRST = 0
            affiliation = crossref_author['affiliation'][FIRST]['name']

        orcid_authors = search_orcid_author(first_name, last_name, affiliation)
        for orcid_author in orcid_authors:
            works = get_orcid_works(orcid_author)
            if check_doi_in_works(paper_doi, works):
                create_orcid_author(orcid_author)


def search_orcid_author(given_names, family_name, affiliation):
    results = []
    # https://pub.orcid.org/v3.0/search/?q="{given_names}%20{family_name}"
    return results


def create_orcid_author(orcid_author):
    # Author.models.create(
    #     first_name=,
    #     last_name=,
    # )
    # SocialAccount.objects.create(
    #     provider=OrcidProvider.id,
    #     uid=orcid_uid,
    #     extra_data=,
    # )
    pass
