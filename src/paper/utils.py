import requests

from django.core.files.base import ContentFile

from utils.http import (
    http_request,
    RequestMethods as methods
)

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

def check_url_contains_pdf(url):
    try:
        r = http_request(methods.HEAD, url, timeout=3)
        content_type = r.headers.get('content-type')
    except Exception as e:
        raise ValidationError(f'Request to {url} failed: {e}')

    if 'application/pdf' not in content_type:
        raise ValueError(
            f'Did not find content type application/pdf at {url}'
        )
    else:
        return True

def get_pdf_from_url(url):
    response = http_request(methods.GET, url, timeout=3)
    pdf = ContentFile(response.content)
    return pdf

