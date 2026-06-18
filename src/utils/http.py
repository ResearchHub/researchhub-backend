import random
import time

import cloudscraper
import requests

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


def scraper_get_url(url: str, timeout: int = 5) -> requests.Response:
    """
    Perform a GET request to retrieve the response headers
    for `url`. If `url` is invalid or returns a bad status code,
    a subclass of `requests.exceptions.RequestException` will be raised.
    """
    scraper = cloudscraper.create_scraper()

    response = scraper.get(url, timeout=timeout, stream=True)
    if response.status_code in (403, 404):
        response.close()  # close previous response
        time.sleep(random.uniform(0, 1))  # wait before retrying
        response = scraper.get(url, timeout=timeout, stream=True)
        response.raise_for_status()

    return response


def check_url_contains_pdf(url) -> bool:
    if url is None:
        return False
    try:
        with scraper_get_url(url) as resp:
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
