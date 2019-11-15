import requests


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


def http_request(method, *args, timeout=1, **kwargs):
    if method == RequestMethods.HEAD:
        return requests.head(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.GET:
        return requests.get(*args, timeout=timeout, **kwargs)
    if method == RequestMethods.POST:
        return requests.post(*args, timeout=timeout, **kwargs)
