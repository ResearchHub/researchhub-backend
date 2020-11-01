from oauth.utils import get_orcid_works, check_doi_in_works
from paper.models import Paper
from paper.utils import download_pdf
from researchhub.celery import app
from utils.orcid import orcid_api
from user.models import Author
from purchase.models import Wallet

VALID_LICENSES = []


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
def create_authors_from_crossref(crossref_authors, paper_id, paper_doi):
    paper = None
    try:
        paper = Paper.objects.get(pk=paper_id)
    except Paper.DoesNotExist:
        pass

    for crossref_author in crossref_authors:
        try:
            first_name = crossref_author['given']
            last_name = crossref_author['family']
        except KeyError:
            break

        affiliation = None
        if len(crossref_author['affiliation']) > 0:
            FIRST = 0
            affiliation = crossref_author['affiliation'][FIRST]['name']

        try:
            orcid_id = crossref_author['ORCID'].split('/')[-1]
            get_or_create_orcid_author(orcid_id, first_name, last_name, paper)
        except KeyError:
            orcid_authors = search_orcid_author(
                first_name,
                last_name,
                affiliation
            )
            for orcid_author in orcid_authors:
                works = get_orcid_works(orcid_author)
                if (len(works) > 0) and check_doi_in_works(paper_doi, works):
                    create_orcid_author(orcid_author, paper)


def search_orcid_author(given_names, family_name, affiliation=None):
    matches = []
    try:
        author_name_results = orcid_api.search_by_name(
            given_names,
            family_name
        )
        authors = author_name_results.json()['result']
        if authors is not None:
            for author in authors:
                uid = author['orcid-identifier']['path']
                author_id_results = orcid_api.search_by_id(uid)
                matches.append(author_id_results.json())
    except Exception as e:
        print(e)
    return matches


def create_orcid_author(orcid_author, paper):
    name = orcid_author['person']['name']
    first_name = name['given-names']['value']
    last_name = name['family-name']['value']
    orcid_id = orcid_author['orcid-identifier']['path']
    get_or_create_orcid_author(orcid_id, first_name, last_name, paper)


def get_or_create_orcid_author(orcid_id, first_name, last_name, paper):
    author, created = Author.models.get_or_create(
        orcid_id=orcid_id,
        defaults={
            'first_name': first_name,
            'last_name': last_name,
        }
    )
    wallet, _ = Wallet.models.get_or_create(
        author=author
    )
    if paper is not None:
        paper.authors.add(author)
