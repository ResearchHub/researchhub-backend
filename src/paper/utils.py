import cloudscraper
import regex as re
import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db.models import Count, Q

from discussion.models import Vote
from paper.exceptions import ManubotProcessingError
from paper.lib import (
    journal_hosts,
    journal_hosts_and_pdf_identifiers,
    journal_pdf_to_url,
    journal_url_to_pdf,
)
from paper.manubot import RHCiteKey
from utils.http import check_url_contains_pdf

DOI_REGEX = r"10.\d{4,9}\/[-._;()\/:a-zA-Z0-9]+?(?=[\";%<>\?#&])"
PAPER_SCORE_Q_ANNOTATION = Count("id", filter=Q(votes__vote_type=Vote.UPVOTE)) - Count(
    "id", filter=Q(votes__vote_type=Vote.DOWNVOTE)
)
SIMILARITY_THRESHOLD = 0.9
MAX_TITLE_PAGES = 5


def check_file_is_url(file):
    if type(file) is str:
        try:
            URLValidator()(file)
        except (ValidationError, Exception):
            return False
        else:
            return True
    return False


def clean_abstract(abstract):
    soup = BeautifulSoup(abstract, "html.parser")
    strings = soup.strings
    cleaned_text = " ".join(strings)
    # cleaned_text = cleaned_text.replace('\n', ' ')
    # cleaned_text = cleaned_text.replace('\r', ' ')
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
        if metadata.get("file", None) is None:
            metadata["file"] = url
        if metadata.get("pdf_url", None) is None:
            metadata["pdf_url"] = url
    return metadata, converted


def convert_journal_url_to_pdf_url(journal_url):
    pdf_url = None
    for host in journal_hosts:
        if host in journal_url:
            if journal_url_to_pdf[host]:
                pdf_url = journal_url_to_pdf[host](journal_url)
                break
    if pdf_url is not None and check_url_contains_pdf(pdf_url):
        return pdf_url, True
    return journal_url, False


def convert_pdf_url_to_journal_url(pdf_url):
    """
    Returns the url and if it was converted as tuple. If not converted the url
    returned is the original pdf url.
    """
    journal_url = None
    for host in journal_hosts:
        if host in pdf_url:
            if journal_pdf_to_url[host]:
                journal_url = journal_pdf_to_url[host](pdf_url)
                break
    if journal_url is not None:
        return journal_url, True
    return pdf_url, False


def get_csl_item(url) -> dict:
    """
    Generate a CSL JSON item for a URL. Currently, does not work
    for most PDF URLs unless they are from known domains where
    persistent identifiers can be extracted.
    """
    from manubot.cite.citekey import citekey_to_csl_item, url_to_citekey

    try:
        citekey = url_to_citekey(url)
        citekey = RHCiteKey(citekey)
        csl_item = citekey_to_csl_item(citekey)

        if not csl_item:
            raise Exception(f"Error searching for paper: {url}")
        return csl_item
    except Exception as e:
        raise ManubotProcessingError(e)


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
    if getattr(csl_item, "url_is_unsupported_pdf", False):
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
    return Unpaywall_Location(
        {
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
        }
    )


def download_pdf(url):
    if check_url_contains_pdf(url):
        pdf = get_pdf_from_url(url)
        filename = url.split("/").pop()
        return pdf, filename
    return None, None


def get_pdf_from_url(url):
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, timeout=3)
    filename = url.split("/").pop()
    if not filename.endswith(".pdf"):
        filename += ".pdf"
    pdf = ContentFile(response.content, name=filename)
    return pdf


def get_cache_key(obj_type, pk):
    return f"{obj_type}_{pk}"


def format_raw_authors(raw_authors):
    for author in raw_authors:
        if "family" in author:
            first_name = author.pop("given", "")
            last_name = author.pop("family", "")

            author["first_name"] = first_name
            author["last_name"] = last_name
        elif "literal" in author:
            name = author.pop("literal", "")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author["first_name"] = first_name
            author["last_name"] = last_name
        elif "author" in author:
            # OpenAlex Cleaning
            author.pop("author_position", None)
            author.pop("institutions", None)
            author.pop("raw_affiliation_string", None)

            author_data = author.pop("author")
            name = author_data.pop("display_name")
            open_alex_id = author_data.pop("id")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author_data["open_alex_id"] = open_alex_id
            author_data["first_name"] = first_name
            author_data["last_name"] = last_name
            author.update(author_data)
        elif "name" in author:
            author.pop("authorId", None)
            name = author.pop("name", "")
            names = name.split(" ")
            first_name = names[0]
            last_name = names[-1]

            author["first_name"] = first_name
            author["last_name"] = last_name

    return raw_authors


def clean_dois(parsed_url, dois):
    netloc = parsed_url.netloc
    if "biorxiv" in netloc:
        version_regex = r"v[0-9]+$"
        dois = list(map(lambda doi: re.sub(version_regex, "", doi), dois))
    return dois


def pdf_copyright_allows_display(paper):
    """
    Returns True if the paper can be displayed on our site.
    E.g. if the paper is open-access and has a license that allows for commercial use.
    """
    oa_status = (
        paper.oa_status or ""
    ).lower()  # Type from https://api.openalex.org/works?group_by=oa_status:include_unknown
    license = (
        paper.pdf_license or ""
    ).lower()  # Type from https://api.openalex.org/works?group_by=primary_location.license:include_unknown
    is_pdf_removed_by_moderator = paper.is_pdf_removed_by_moderator

    # we're going to assume that if a moderator removed it,
    # it was because of copyright issues
    if is_pdf_removed_by_moderator:
        return False

    # If the license starts with cc-by, it allows for commercial use
    if license.startswith("cc-by"):
        return True

    # In addition, we can only show the following licenses allowed for commercial use
    if license in [
        "public-domain",
        "mit",
        "pd",
    ]:
        return True

    # only rely on oa_status if license is null or unknown
    # otherwise license is non-usable for us
    if license in [None, "", "unknown", "unspecified-oa"]:
        if oa_status in [None, "", "green", "gold"]:
            return True

    return False
