import requests


# TODO: Use contstants instead of class
GET = 'GET'
HEAD = 'HEAD'
POST = 'POST'
PATCH = 'PATCH'
PUT = 'PUT'
DELETE = 'DELETE'


class RequestMethods:
    GET = 'GET'
    HEAD = 'HEAD'
    POST = 'POST'
    PATCH = 'PATCH'
    PUT = 'PUT'
    DELETE = 'DELETE'


def get_user_from_request(ctx):
    request = ctx.get('request')
    if request and hasattr(request, 'user'):
        return request.user
    return None


def http_request(
        method, *args, timeout=300, **kwargs) -> requests.models.Response:
    '''
    Returns an http response.

    Args:
        method (str) -- One of "GET", "HEAD", "DELETE", "POST", "PUT", "PATCH"
        url (str)

    Optional:
        params (dict)
        data (str)
        timeout (float) -- Defaults to 300s
        headers (dict)
    '''
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


def check_url_contains_pdf(url) -> bool:
    if url is None:
        return False
    try:
        headers = get_url_headers(url)
        content_type = headers.get('content-type', '')
        return 'application/pdf' in content_type
    except Exception:
        return False
