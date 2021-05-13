import io
import requests
import fitz
import jellyfish
import nltk

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from datetime import datetime
from habanero import Crossref
from manubot.cite.csl_item import CSL_Item
from bs4 import BeautifulSoup
from utils import sentry

from paper.lib import (
    journal_hosts,
    journal_hosts_and_pdf_identifiers,
    journal_pdf_to_url,
    journal_url_to_pdf
)

from utils.http import (
    check_url_contains_pdf,
    http_request,
    RequestMethods as methods
)

CACHE_TOP_RATED_DATES = (
    '-score_today',
    '-score_week',
    '-score_month',
    '-score_year',
    '-score_all_time'
)
CACHE_MOST_DISCUSSED_DATES = (
    '-discussed_today',
    '-discussed_week',
    '-discussed_month',
    '-discussed_year',
    '-discussed_all_time'
)
MANUBOT_PAPER_TYPES = [
    'paper-conference',
    'article-journal',
]
SIMILARITY_THRESHOLD = 0.9
MAX_TITLE_PAGES = 5
IGNORE_PAPER_TITLES = [
    'editorial',
    'editorial board',
    'contents continued',
    'table of contents',
    'calendar',
    'copyright',
    'contributors',
    'contents',
    'ieee access',
    'correspondence',
    'announcements',
    'editorial advisory board',
    'issue highlights',
    'title page',
    'front cover'
]


def check_file_is_url(file):
    if (type(file) is str):
        try:
            URLValidator()(file)
        except (ValidationError, Exception):
            return False
        else:
            return True
    return False


def clean_abstract(abstract):
    soup = BeautifulSoup(abstract, 'html.parser')
    strings = soup.strings
    cleaned_text = ' '.join(strings)
    cleaned_text = cleaned_text.replace('\n', ' ')
    cleaned_text = cleaned_text.replace('\r', ' ')
    cleaned_text = cleaned_text.lstrip()
    return cleaned_text


def check_url_is_pdf(url):
    """
    Checks if the url is a from a journal and is a pdf.
    Returns true if the above requirements are met, false
    if the url is from the journal but not a pdf, and none
    if both requirements are not met.
    """
    for host, pdf_identifier in journal_hosts_and_pdf_identifiers:
        if host in url and pdf_identifier in url:
            return True
        elif host in url and pdf_identifier not in url:
            return False
    return None


def populate_pdf_url_from_journal_url(url, metadata):
    """
    Returns tuple of:
    metadata with pdf_url and file if pdf is found
    and whether this fills the metadata or not.
    """
    url, converted = convert_journal_url_to_pdf_url(url)
    if converted and check_url_contains_pdf(url):
        if metadata.get('file', None) is None:
            metadata['file'] = url
        if metadata.get('pdf_url', None) is None:
            metadata['pdf_url'] = url
    return metadata, False


def convert_journal_url_to_pdf_url(journal_url):
    pdf_url = None
    for host in journal_hosts:
        if host in journal_url:
            pdf_url = journal_url_to_pdf[host](journal_url)
            break
    if pdf_url is not None:
        return pdf_url, True
    return journal_url, False


def populate_metadata_from_manubot_pdf_url(url, metadata):
    journal_url, converted = convert_pdf_url_to_journal_url(url)
    if converted:
        metadata['url'] = journal_url
        metadata['pdf_url'] = url
    return populate_metadata_from_manubot_url(journal_url, metadata)


def convert_pdf_url_to_journal_url(pdf_url):
    """
    Returns the url and if it was converted as tuple. If not converted the url
    returned is the original pdf url.
    """
    journal_url = None
    for host in journal_hosts:
        if host in pdf_url:
            journal_url = journal_pdf_to_url[host](pdf_url)
            break
    if journal_url is not None:
        return journal_url, True
    return pdf_url, False


def populate_metadata_from_manubot_url(url, metadata):
    """
    Returns metadata dictionary populated with manubot csl item data or None
    if manubot fails to retrieve data,
    and whether this fills the metadata or not.
    """
    try:
        csl_item = get_csl_item(url)
        if not isinstance(csl_item, CSL_Item):
            csl_item = CSL_Item(csl_item)

        # TODO: We can use this if we want to reject uploads that don't match
        # certain content types
        #
        # if csl_item['type'] not in MANUBOT_PAPER_TYPES:
        #     return None

        doi = None
        if 'DOI' in csl_item:
            doi = csl_item['DOI'].lower()

        paper_publish_date = csl_item.get_date('issued', fill=True)

        data = {}
        data["abstract"] = csl_item.get('abstract', None)
        data["doi"] = doi
        data["is_public"] = True
        data["paper_title"] = csl_item.get('title', None)
        data["csl_item"] = csl_item
        data["paper_publish_date"] = paper_publish_date
        data["raw_authors"] = get_raw_authors_from_csl_item(csl_item)

        metadata.update(data)
        return metadata, True
    except Exception as e:
        print(e)
        return None, False


def populate_metadata_from_pdf(file, validated_data):
    # TODO: Use old pdf metadata method?
    try:
        date_format = 'D:%Y%m%d%H%M%S'
        doc = fitz.open(stream=file.read(), filetype='pdf')
        metadata = doc.metadata

        date = metadata.get('creationDate').split('+')[0].strip('Z')
        title = metadata.get('title')
        author = metadata.get('author')

        if author:
            name = author.split(' ')
            if len(name) < 1:
                first_name = name[0]
                last_name = ''
            else:
                first_name = name[0]
                last_name = name[len(name) - 1]
            author = [
                {'first_name': first_name, 'last_name': last_name}
            ]
            validated_data['raw_authors'] = author

        if title:
            validated_data['paper_title'] = title
        validated_data['paper_publish_date'] = datetime.strptime(
            date,
            date_format
        )

        return validated_data, True
    except Exception as e:
        print(e)
        return None, False


def populate_metadata_from_crossref(url, validated_data):
    try:
        doi = validated_data.get('doi')
        paper_title = validated_data.get('paper_title')

        cr = Crossref()
        params = {
            'filters': {'type': 'journal-article'},
        }

        if doi:
            params['ids'] = [doi]
        else:
            params['query_bibliographic'] = paper_title
            params['limit'] = 1
            params['order'] = 'desc'
            params['sort'] = 'score'

        results = cr.works(
            **params
        )['message']

        if 'items' in results:
            data = results['items'][0]
        else:
            data = results['message']

        validated_data = {}
        validated_data['doi'] = doi
        validated_data['abstract'] = clean_abstract(data.get('abstract', ''))
        validated_data['is_public'] = True
        validated_data['paper_title'] = data.get('title', [''])[0]
        validated_data['paper_publish_date'] = data.get(
            'created'
        ).get(
            'date-time'
        )
        validated_data['raw_authors'] = get_raw_authors_from_csl_item(data)

        return validated_data, True
    except Exception as e:
        print(e)
        return None, False


def get_raw_authors_from_csl_item(csl_item):
    authors = csl_item.get('author', None)
    if authors is None:
        return
    raw_authors = []
    for author in authors:
        try:
            raw_authors.append({
                'first_name': author['given'],
                'last_name': author['family']
            })
        except Exception as e:
            print(f'Failed to construct author: {author}', e)
    return raw_authors


def get_csl_item(url) -> dict:
    """
    Generate a CSL JSON item for a URL. Currently, does not work
    for most PDF URLs unless they are from known domains where
    persistent identifiers can be extracted.
    """
    from manubot.cite.citekey import (
        CiteKey, citekey_to_csl_item, url_to_citekey)
    citekey = url_to_citekey(url)
    citekey = CiteKey(citekey).standard_id
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


def get_redirect_url(url):
    response = http_request(methods.GET, url, allow_redirects=False)
    status_code = response.status_code
    if status_code == 301 or status_code == 302 or status_code == 303:
        headers = response.headers
        location = headers.get('Location')
        if location:
            return location
        else:
            return None
    elif status_code == 200:
        return url
    return None


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


def clean_pdf(file):
    researchgate_1 = 'ResearchGate'
    researchgate_2 = 'Some of the authors of this publication are also working on these related projects'
    researchgate_3 = 'CITATIONS'
    researchgate_4 = 'READS'

    researchgate_strings = (
        researchgate_1,
        researchgate_2,
        researchgate_3,
        researchgate_4
    )
    try:
        doc = fitz.open(stream=file.read(), filetype='pdf')
        if doc.pageCount <= 1:
            return

        found_items = 0
        first_page = doc[0]
        for researchgate_str in researchgate_strings:
            if first_page.searchFor(researchgate_str):
                found_items += 1

        if found_items >= 3:
            doc.deletePage(0)
            pdf_bytes = io.BytesIO(doc.write())
            file.file = pdf_bytes
    except Exception as e:
        sentry.log_error(e)
    finally:
        file.seek(0)


def check_pdf_title(input_title, file):
    if not input_title or not file:
        return False

    try:
        clean_pdf(file)
        doc = fitz.open(stream=file.read(), filetype='pdf')
        doc_metadata = doc.metadata
        doc_title = doc_metadata.get('title') or ''

        # Lowercasing titles for simple normalization
        normalized_input_title = input_title.lower()
        normalized_pdf_title = doc_title.lower()

        # Checks if the title matches the pdf's metadata first
        similar = check_similarity(
            normalized_pdf_title,
            normalized_input_title
        )

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


def reset_paper_cache(cache_key, data):
    cache.set(cache_key, data, timeout=60*60*24*7)


def reset_cache(
    hub_ids,
    ordering='-hot_score',
    time_difference=0
):
    from paper.tasks import preload_trending_papers, celery_preload_hub_papers

    context = {}
    context['user_no_balance'] = True
    context['exclude_promoted_score'] = True
    context['include_wallet'] = False

    for hub_id in hub_ids:
        preload_trending_papers.apply_async(
            (
                hub_id,
                ordering,
                time_difference,
                context
            ),
            priority=1
        )
    celery_preload_hub_papers.apply_async(
        (hub_ids,),
        priority=1
    )


def get_cache_key(obj_type, pk):
    return f'{obj_type}_{pk}'


def add_default_hub(hub_ids):
    if 0 not in hub_ids:
        return [0] + list(hub_ids)
    return hub_ids


def invalidate_trending_cache(hub_ids, with_default=True):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        cache_key = get_cache_key(
            'hub',
            f'{hub_id}_-hot_score_today'
        )
        cache.delete(cache_key)


def invalidate_top_rated_cache(hub_ids, with_default=True):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for key in CACHE_TOP_RATED_DATES:
            cache_key = get_cache_key(
                'hub',
                f'{hub_id}_{key}'
            )
            cache.delete(cache_key)


def invalidate_newest_cache(hub_ids, with_default=True):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        cache_key = get_cache_key(
            'hub',
            f'{hub_id}_-uploaded_date_today'
        )
        cache.delete(cache_key)


def invalidate_most_discussed_cache(hub_ids, with_default=True):
    if with_default:
        hub_ids = add_default_hub(hub_ids)

    for hub_id in hub_ids:
        for key in CACHE_MOST_DISCUSSED_DATES:
            cache_key = get_cache_key(
                'hub',
                f'{hub_id}_{key}'
            )
            cache.delete(cache_key)
