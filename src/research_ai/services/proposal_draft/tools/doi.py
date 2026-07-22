"""Shared DOI string helpers for the proposal toolset.

Pure string munging the proposal tools and the draft driver both need: strip a
known DOI/DOI-URL prefix down to a bare, comparable key, or render a DOI as a
resolvable URL. Kept here (not in ``utils.doi``) on purpose -- ``utils.doi.DOI``
imports the paper/post/user models and lowercases what it normalizes, neither
of which these lightweight, model-free call sites want.
"""

# Known DOI / DOI-URL prefixes, longest-to-shortest is not required since each is
# matched against the start of the string independently.
_DOI_URL_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",  # NOSONAR - prefix match for normalization, not a request
    "https://dx.doi.org/",
    "doi:",
)


def doi_url(doi: object) -> str:
    """A citation's DOI as a resolvable URL (bare DOIs get the doi.org prefix).

    Existing http(s) URLs pass through untouched and casing is preserved --
    this renders for display, it does not build a comparison key (that is
    ``strip_doi_prefix``).
    """
    raw = str(doi or "").strip()
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")):  # NOSONAR - scheme check, not a request
        return raw
    return f"https://doi.org/{raw}"


def strip_doi_prefix(value: object) -> str:
    """Lowercase ``value`` and strip a known DOI/DOI-URL prefix.

    Returns the bare remainder when a prefix matched, else the lowercased string
    unchanged. This is pure normalization -- callers decide what a remainder that
    is not actually a DOI means (a comparison key vs. a lookup DOI).
    """
    s = str(value or "").strip().lower()
    for prefix in _DOI_URL_PREFIXES:
        if s.startswith(prefix):
            return s[len(prefix) :]
    return s
