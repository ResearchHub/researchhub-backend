from paper.models import Paper
from search.tasks import queue_get_authors_from_doi, queue_download_pdf


valid_licenses = []


def create_paper_from_crossref(item):
    # queue_get_authors_from_doi(item['author'])
    # TODO: queue
    download_pdf_by_license(item)

    return Paper.objects.create(
        title=item['title'][0],
        doi=item['DOI'],
        url=item['URL'],
        # paper_publish_date=get_crossref_publish_date_parts(item),  # TODO:
        # pdf=file,
    )


def download_pdf_by_license(item):
    try:
        licenses = item['license']
        for license in licenses:
            if license in valid_licenses:
                get_pdf(item['links'])
                break
    except Exception:
        pass


def get_pdf(links):
    for link in links:
        if link['content-type'] == 'application/pdf':
            return queue_download_pdf(link['URL'])
    return None
