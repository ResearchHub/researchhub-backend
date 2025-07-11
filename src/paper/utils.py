import io
import math
from datetime import datetime

import cloudscraper
import fitz
import jellyfish
import regex as re
import requests
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db import models
from django.db.models import Count, Q
from habanero import Crossref
from manubot.cite.csl_item import CSL_Item

from discussion.models import Vote
from paper.exceptions import ManubotProcessingError
from paper.lib import (
    journal_hosts,
    journal_hosts_and_pdf_identifiers,
    journal_pdf_to_url,
    journal_url_to_pdf,
)
from paper.manubot import RHCiteKey
from utils import sentry
from utils.http import RequestMethods as methods
from utils.http import check_url_contains_pdf, http_request

DOI_REGEX = r"10.\d{4,9}\/[-._;()\/:a-zA-Z0-9]+?(?=[\";%<>\?#&])"
PAPER_SCORE_Q_ANNOTATION = Count("id", filter=Q(votes__vote_type=Vote.UPVOTE)) - Count(
    "id", filter=Q(votes__vote_type=Vote.DOWNVOTE)
)

CACHE_TOP_RATED_DATES = (
    "-score_today",
    "-score_week",
    "-score_month",
    "-score_year",
    "-score_all_time",
)
CACHE_MOST_DISCUSSED_DATES = (
    "-discussed_today",
    "-discussed_week",
    "-discussed_month",
    "-discussed_year",
    "-discussed_all_time",
)
CACHE_DOCUMENT_TYPES = (
    "all",
    "paper",
    "posts",
    "hypothesis",
)
MANUBOT_PAPER_TYPES = [
    "paper-conference",
    "article-journal",
]
SIMILARITY_THRESHOLD = 0.9
MAX_TITLE_PAGES = 5
IGNORE_PAPER_TITLES = [
    "editorial",
    "editorial board",
    "contents continued",
    "table of contents",
    "calendar",
    "copyright",
    "contributors",
    "contents",
    "ieee access",
    "correspondence",
    "announcements",
    "editorial advisory board",
    "issue highlights",
    "title page",
    "front cover",
]


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


def populate_metadata_from_manubot_pdf_url(url, metadata):
    journal_url, converted = convert_pdf_url_to_journal_url(url)
    if converted:
        metadata["url"] = journal_url
        metadata["pdf_url"] = url
    return populate_metadata_from_manubot_url(journal_url, metadata)


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
        if "DOI" in csl_item:
            doi = csl_item["DOI"].lower()

        paper_publish_date = csl_item.get_date("issued", fill=True)

        data = {}
        data["abstract"] = csl_item.get("abstract", None)
        data["doi"] = doi
        data["is_public"] = True
        data["paper_title"] = csl_item.get("title", None)
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
        date_format = "D:%Y%m%d%H%M%S"
        doc = fitz.open(stream=file.read(), filetype="pdf")
        metadata = doc.metadata

        date = metadata.get("creationDate").split("+")[0].strip("Z")
        title = metadata.get("title")
        author = metadata.get("author")

        if author:
            name = author.split(" ")
            if len(name) < 1:
                first_name = name[0]
                last_name = ""
            else:
                first_name = name[0]
                last_name = name[len(name) - 1]
            author = [{"first_name": first_name, "last_name": last_name}]
            validated_data["raw_authors"] = author

        if title:
            validated_data["paper_title"] = title
        validated_data["paper_publish_date"] = datetime.strptime(date, date_format)

        return validated_data, True
    except Exception as e:
        print(e)
        return None, False


def populate_metadata_from_crossref(url, validated_data):
    try:
        doi = validated_data.get("doi")
        paper_title = validated_data.get("paper_title")

        cr = Crossref()
        params = {
            "filters": {"type": "journal-article"},
        }

        if doi:
            params["ids"] = [doi]
        else:
            params["query_bibliographic"] = paper_title
            params["limit"] = 1
            params["order"] = "desc"
            params["sort"] = "score"

        results = cr.works(**params)["message"]

        if "items" in results:
            data = results["items"][0]
        else:
            data = results["message"]

        validated_data = {}
        validated_data["doi"] = doi
        validated_data["abstract"] = clean_abstract(data.get("abstract", ""))
        validated_data["is_public"] = True
        validated_data["paper_title"] = data.get("title", [""])[0]
        validated_data["paper_publish_date"] = data.get("created").get("date-time")
        validated_data["raw_authors"] = get_raw_authors_from_csl_item(data)

        return validated_data, True
    except Exception as e:
        print(e)
        return None, False


def get_raw_authors_from_csl_item(csl_item):
    authors = csl_item.get("author", None)
    if authors is None:
        return
    raw_authors = []
    for author in authors:
        try:
            raw_authors.append(
                {"first_name": author["given"], "last_name": author["family"]}
            )
        except Exception as e:
            print(f"Failed to construct author: {author}", e)
    return raw_authors


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


def get_redirect_url(url):
    response = http_request(methods.GET, url, allow_redirects=False)
    status_code = response.status_code
    if status_code == 301 or status_code == 302 or status_code == 303:
        headers = response.headers
        location = headers.get("Location")
        if location:
            return location
        else:
            return None
    elif status_code == 200:
        return url
    return None


def clean_pdf(file):
    researchgate_1 = "ResearchGate"
    researchgate_2 = "Some of the authors of this publication are also working on these related projects"
    researchgate_3 = "CITATIONS"
    researchgate_4 = "READS"

    researchgate_strings = (
        researchgate_1,
        researchgate_2,
        researchgate_3,
        researchgate_4,
    )
    try:
        doc = fitz.open(stream=file.read(), filetype="pdf")
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
        doc = fitz.open(stream=file.read(), filetype="pdf")
        doc_metadata = doc.metadata
        doc_title = doc_metadata.get("title") or ""

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
                ngrams = _ngrams(page_text.split(), n_length)
                for ngram in ngrams:
                    ngram_string = " ".join(ngram)
                    similar = check_similarity(ngram_string, normalized_input_title)
                    if similar:
                        return True
        return False
    except Exception as e:
        print(e)


def _ngrams(words: list, n: int) -> list:
    """
    Returns a list of ngrams of size n from the given list of words.
    """
    return zip(*[words[i:] for i in range(n)])


def check_crossref_title(original_title, crossref_title):
    # Lowercasing titles for simple normalization
    normalized_original_title = original_title.lower()
    normalized_crossref_title = crossref_title.lower()

    similar = check_similarity(normalized_original_title, normalized_crossref_title)

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
    filters = {"type": "journal-article"}
    limit = 10
    sort = "score"
    order = "desc"
    results = cr.works(
        query_bibliographic=query,
        filters=filters,
        limit=limit,
        sort=sort,
        order=order,
    )
    results = results["message"]["items"]
    return results[:index]


def get_cache_key(obj_type, pk):
    return f"{obj_type}_{pk}"


def add_default_hub(hub_ids):
    if 0 not in hub_ids:
        return [0] + list(hub_ids)
    return hub_ids


def parse_author_name(author):
    full_name = []

    if isinstance(author, models.Model):
        if getattr(author, "first_name") and not is_blank_str(
            getattr(author, "first_name")
        ):
            full_name.append(author.first_name)
        if getattr(author, "last_name") and not is_blank_str(
            getattr(author, "last_name")
        ):
            full_name.append(author.last_name)

    elif isinstance(author, dict):
        if author.get("first_name") and not is_blank_str(author.get("first_name")):
            full_name.append(author.get("first_name"))
        if author.get("last_name") and not is_blank_str(author.get("last_name")):
            full_name.append(author.get("last_name"))

    elif isinstance(author, str) and not is_blank_str(author):
        full_name.append(author)

    return " ".join(full_name)


def is_blank_str(string):
    if string and isinstance(string, str) and string.strip() != "":
        return False

    return True


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
