import urllib.parse
from urllib.parse import urlparse, urlunparse

import cloudscraper
import requests
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def remove_origin_from_url(url):
    # Parse the URL into components
    parsed_url = urlparse(url)

    # Remove the leading slash from the path if it exists
    path = parsed_url.path
    if path.startswith("/"):
        path = path[1:]

    # Reconstruct the URL without the scheme and netloc, and with the modified path
    non_origin_url = urlunparse(
        ("", "", path, parsed_url.params, parsed_url.query, parsed_url.fragment)
    )

    return non_origin_url


def clean_url(url):
    """
    Clean and validate a URL.

    Args:
        url (str): The URL to clean and validate

    Returns:
        str or None: The cleaned URL if valid, None otherwise

    This function:
    1. Strips whitespace from the URL
    2. URL encodes it properly with safe characters
    3. Validates the URL using Django's URLValidator
    4. Returns None if validation fails
    """
    if not url:
        return None

    url = url.strip()
    url = urllib.parse.quote(url, safe=":/?&=")

    validate = URLValidator()
    try:
        validate(url)
    except ValidationError:
        return None

    return url


# TODO: Use contstants instead of class
GET = "GET"
HEAD = "HEAD"
POST = "POST"
PATCH = "PATCH"
PUT = "PUT"
DELETE = "DELETE"


class RequestMethods:
    GET = "GET"
    HEAD = "HEAD"
    POST = "POST"
    PATCH = "PATCH"
    PUT = "PUT"
    DELETE = "DELETE"


def get_user_from_request(ctx):
    request = ctx.get("request")
    if request and hasattr(request, "user"):
        return request.user
    return None


def http_request(method, *args, timeout=300, **kwargs) -> requests.models.Response:
    """
    Returns an http response.

    Args:
        method (str) -- One of "GET", "HEAD", "DELETE", "POST", "PUT", "PATCH"
        url (str)

    Optional:
        params (dict)
        data (str)
        timeout (float) -- Defaults to 300s
        headers (dict)
    """
    if method == RequestMethods.DELETE:
        return requests.delete(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.HEAD:
        return requests.head(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.GET:
        return requests.get(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.POST:
        return requests.post(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.PUT:
        return requests.put(*args, timeout=timeout, **kwargs)


def get_url_headers(url: str) -> requests.structures.CaseInsensitiveDict:
    """
    Perform a HEAD request to retrieve the response headers
    for `url`. If `url` is invalid or returns a bad status code,
    a subclass of `requests.exceptions.RequestException` will be raised.
    """
    response = http_request(HEAD, url, timeout=2)
    if (response.status_code == 404) or (response.status_code == 403):
        response = http_request(GET, url, timeout=2)
        response.raise_for_status()
    return response.headers


def scraper_get_url(url: str) -> requests.structures.CaseInsensitiveDict:
    """
    Perform a GET request to retrieve the response headers
    for `url`. If `url` is invalid or returns a bad status code,
    a subclass of `requests.exceptions.RequestException` will be raised.
    """
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url, timeout=2)
    if (response.status_code == 404) or (response.status_code == 403):
        response = scraper.get(url, timeout=2)
        response.raise_for_status()
    return response


def check_url_contains_pdf(url) -> bool:
    if url is None:
        return False
    try:
        resp = scraper_get_url(url)
        if "sciencedirect" in url and "download=false" in url:
            return resp.status_code < 400

        headers = resp.headers
        content_type = headers.get("content-type", "")
        filename = headers.get("filename", "")
        return "application/pdf" in content_type or ".pdf" in filename
    except Exception:
        return False


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip
