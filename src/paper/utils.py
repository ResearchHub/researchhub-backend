import cloudscraper
from bs4 import BeautifulSoup
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import URLValidator
from django.db.models import Count, Q

from discussion.models import Vote
from paper.exceptions import ManubotProcessingError
from paper.manubot import RHCiteKey

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


def download_pdf_from_url(url: str) -> ContentFile:
    """
    Downloads a PDF from a URL and validates that it's actually a PDF.

    Raises:
        ValueError: If the URL does not point to a PDF file
    """
    scraper = cloudscraper.create_scraper()
    with scraper.get(url, timeout=60) as response:
        response.raise_for_status()

        # Validate that the response is a PDF
        content_type = response.headers.get("content-type", "").lower()
        filename_header = response.headers.get("filename", "").lower()
        is_pdf = "application/pdf" in content_type or ".pdf" in filename_header

        if not is_pdf:
            raise ValueError(
                f"URL does not point to a PDF file. Content-Type: {content_type}"
            )

        content = response.content

    filename = url.split("/").pop()
    if not filename.endswith(".pdf"):
        filename += ".pdf"
    pdf = ContentFile(content, name=filename)
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
    if license in [None, "", "unknown", "unspecified-oa"] and oa_status in [
        None,
        "",
        "green",
        "gold",
    ]:
        return True

    return False
