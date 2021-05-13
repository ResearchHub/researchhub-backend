class DisableCSRF(object):
    """Middleware for disabling CSRF in an specified app name.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if 'google' in request.path_info:
            setattr(request, '_dont_enforce_csrf_checks', True)
        return self.get_response(request)
