import requests

import fitz
import jellyfish
import nltk

from django.core.files.base import ContentFile
from habanero import Crossref

from utils.http import (
    check_url_contains_pdf,
    http_request,
    RequestMethods as methods
)
from utils import sentry


MANUBOT_PAPER_TYPES = [
    'paper-conference',
    'article-journal',
]
SIMILARITY_THRESHOLD = 0.9
MAX_TITLE_PAGES = 5


def get_csl_item(url) -> dict:
    """
    Generate a CSL JSON item for a URL. Currently, does not work
    for most PDF URLs unless they are from known domains where
    persistent identifiers can be extracted.
    """
    from manubot.cite.citekey import (
        citekey_to_csl_item, standardize_citekey, url_to_citekey)
    citekey = url_to_citekey(url)
    citekey = standardize_citekey(citekey)
    csl_item = citekey_to_csl_item(citekey)
    return csl_item


def get_pdf_location_for_csl_item(csl_item):
    """
    Get best open access location with a PDF,
    with preference to a location with an OA license.
    Uses `manubot.cite.unpaywall` which currently supports
    DOIs and arXiv IDs. Returns an Unpaywall OA Location data structure
    described at <http://unpaywall.org/data-format#oa-location-object>.
    """
    from manubot.cite.unpaywall import Unpaywall
    if not csl_item:
        return None
    # CSL_Item.url_is_unsupported_pdf is a non-standard field that
    # upstream functions can set to specify that metadata could not
    # be automatically generated for a PDF URL.
    if getattr(csl_item, 'url_is_unsupported_pdf', False):
        return get_location_for_unsupported_pdf(csl_item)
    try:
        upw = Unpaywall.from_csl_item(csl_item)
    except (ValueError, requests.RequestException):
        return None
    oa_location = upw.best_openly_licensed_pdf or upw.best_pdf
    return oa_location


def get_location_for_unsupported_pdf(csl_item):
    """
    For CSL Items with url_is_unsupported_pdf, the URL is PDF
    from an unsupported domain, meaning no CSL metadata can be
    generated. However, since URL resolves to a PDF, we can
    provide an Unpaywall_Location pointing to that URL.
    """
    import datetime
    from manubot.cite.unpaywall import Unpaywall_Location

    url = csl_item.get("URL")
    return Unpaywall_Location({
        "endpoint_id": None,
        "evidence": None,
        "host_type": None,
        "is_best": True,
        "license": None,
        "pmh_id": None,
        "repository_institution": None,
        "updated": datetime.datetime.now().isoformat(),
        "url": url,
        "url_for_landing_page": None,
        "url_for_pdf": url,
        "version": None,
    })


def download_pdf(url):
    if check_url_contains_pdf(url):
        pdf = get_pdf_from_url(url)
        filename = url.split('/').pop()
        return pdf, filename


def get_pdf_from_url(url):
    response = http_request(methods.GET, url, timeout=3)
    pdf = ContentFile(response.content)
    return pdf


def fitz_extract_xobj(file_path):
    src = fitz.open(file_path)  # open input
    doc = fitz.open()  # output file
    xobj_total = 0  # counts total number of extracted xobjects
    xrefs_encountered = []  # stores already extracted XObjects
    for pno in range(len(src)):
        xobj_count = 0  # counts extracted objects per page
        xobj_list = src.getPageXObjectList(pno)  # get list of XObjects
        for xobj in xobj_list:  # loop through them
            if xobj[2] != 0:  # if not occurring directly on the page
                continue  # skip
            bbox = fitz.Rect(xobj[-1])  # bbox of XObject on input page
            if bbox.isInfinite:  # no associated valid bbox?
                continue  # skip
            if xobj[0] in xrefs_encountered:  # already extracted?
                continue  # skip
            xrefs_encountered.append(xobj[0])
            # ----------------------------------------------------------------------
            # We want this XObject, so:
            # (1) copy its page to the output PDF (enforcing zero rotation)
            # (2) from that page remove everything except the XObject
            # (3) modify page size to match the XObject bbox
            # ----------------------------------------------------------------------
            doc.insertPDF(src, from_page=pno, to_page=pno, rotate=0)
            ref_name = xobj[1]  # the symbolic name
            ref_cmd = (f'/{ref_name} Do').encode()  # build invocation command
            page = doc[-1]  # page just inserted
            page.setMediaBox(bbox)  # set its page size to XObject bbox
            page.cleanContents()  # consolidate contents of copied page
            xref = page.getContents()[0]  # and read resulting singular xref
            doc.updateStream(xref, ref_cmd)  # replace it by our one-line cmd
            xobj_count += 1  # increase counter

        xobj_total += xobj_count  # increase total xobject count

    if xobj_total > 0:
        for page in doc:
            pix = page.getPixmap(alpha=False)
            pix.writePNG(f'{file_path}-{page.number}.png')
    else:
        print(f'No XObjects detected in {file_path}, no output generated.')


def fitz_extract_figures(file_path):
    doc = fitz.open(file_path)
    for i in range(len(doc)):
        for img in doc.getPageImageList(i):
            xref = img[0]  # check if this xref was handled already?
            pix = fitz.Pixmap(doc, xref)
            if pix.colorspace is None:
                continue
            else:  # CMYK needs to be converted to RGB first
                pix1 = fitz.Pixmap(fitz.csRGB, pix)  # make RGB pixmap copy
                pix1.writePNG(f'{file_path}-p{i}-{xref}.png')
                pix1 = None  # release storage early (optional)
            pix = None  # release storage early (optional)
    fitz_extract_xobj(file_path)


def check_pdf_title(input_title, file):
    if not input_title or not file:
        return False

    try:
        doc = fitz.open(stream=file.read(), filetype='pdf')
        doc_metadata = doc.metadata
        doc_title = doc_metadata.get('title') or ''

        # Lowercasing titles for simple normalization
        normalized_input_title = input_title.lower()
        normalized_pdf_title = doc_title.lower()

        # Checks if the title matches the pdf's metadata first
        similar = check_similarity(normalized_pdf_title, normalized_input_title)

        if similar:
            return True
        else:
            n_length = len(normalized_input_title.split())
            for i, page in enumerate(doc):
                if i > MAX_TITLE_PAGES:
                    return False

                page_text = page.getText().lower()
                if normalized_input_title in page_text:
                    return True
                ngrams = nltk.ngrams(page_text.split(), n_length)
                for ngram in ngrams:
                    ngram_string = ' '.join(ngram)
                    similar = check_similarity(
                        ngram_string,
                        normalized_input_title
                    )
                    if similar:
                        return True
        return False
    except Exception as e:
        print(e)


def check_crossref_title(original_title, crossref_title):
    # Lowercasing titles for simple normalization
    normalized_original_title = original_title.lower()
    normalized_crossref_title = crossref_title.lower()

    similar = check_similarity(
        normalized_original_title,
        normalized_crossref_title
    )

    if similar:
        return True
    return False


def get_cache_key(request, subtype, pk=None):
    if pk is None:
        paper_id = request.path.split('/')[3]
    else:
        paper_id = pk
    key = f'get_paper_{paper_id}_{subtype}'
    return key


def check_similarity(str1, str2, threshold=SIMILARITY_THRESHOLD):
    r = jellyfish.jaro_distance(str1, str2)
    if r >= threshold:
        return True
    return False


def get_crossref_results(query, index=10):
    cr = Crossref()
    filters = {'type': 'journal-article'}
    limit = 10
    sort = 'score'
    order = 'desc'
    results = cr.works(
        query_bibliographic=query,
        filters=filters,
        limit=limit,
        sort=sort,
        order=order,
    )
    results = results['message']['items']
    return results[:index]


def merge_paper_votes(original_paper, new_paper):
    old_votes = original_paper.votes.all()
    old_votes_user = old_votes.values_list(
        'created_by_id',
        flat=True
    )
    conflicting_votes = new_paper.votes.filter(
        created_by__in=old_votes_user
    )
    conflicting_votes_user = conflicting_votes.values_list(
        'created_by_id',
        flat=True
    )
    new_votes = new_paper.votes.exclude(
        created_by_id__in=conflicting_votes_user
    )

    # Delete conflicting votes from the new paper
    conflicting_votes.delete()

    # Transfer new votes to original paper
    new_votes.update(paper=original_paper)


def merge_paper_threads(original_paper, new_paper):
    new_paper.threads.update(paper=original_paper)


def merge_paper_bulletpoints(original_paper, new_paper):
    original_bullet_points = original_paper.bullet_points.all()
    new_bullet_points = new_paper.bullet_points.all()
    for new_bullet_point in new_bullet_points:
        new_point_text = new_bullet_point.plain_text
        for original_bullet_point in original_bullet_points:
            original_point_text = original_bullet_point.plain_text
            is_similar = check_similarity(original_point_text, new_point_text)
            if not is_similar:
                new_bullet_point.paper = original_paper
                new_bullet_point.save()
            else:
                new_bullet_point.delete()
