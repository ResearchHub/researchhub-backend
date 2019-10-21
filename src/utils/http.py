class RequestMethods:
    POST = 'POST'
    PATCH = 'PATCH'
    PUT = 'PUT'
    DELETE = 'DELETE'


def get_user_from_request(ctx):
    request = ctx.get('request')
    if request and hasattr(request, 'user'):
        return request.user
    return None
