
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
