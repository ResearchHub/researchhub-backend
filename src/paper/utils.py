
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


def get_best_oa_location_for_csl_item(csl_item):
    from manubot.cite.unpaywall import Unpaywall
    upw = Unpaywall.from_csl_item(csl_item)
    # get best open access location with a license,
    # with preference to a location with an OA license
    oa_location = upw.best_openly_licensed_pdf or upw.best_pdf
    return oa_location




