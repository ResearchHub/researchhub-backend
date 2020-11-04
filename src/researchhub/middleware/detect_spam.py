from utils import sentry
from researchhub.settings import geo_ip

class DetectSpam(object):
    """Middleware for disabling CSRF in an specified app name.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # if 'google' in request.path_info:
        #     setattr(request, '_dont_enforce_csrf_checks', True)

        response = self.get_response(request)

        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')

        if request.user.is_authenticated and not request.user.probable_spammer:
            try:
                country = geo_ip.country(ip)
                if country.get('country_code') == 'ID':
                    request.user.set_probable_spammer()
            except Exception as e:
                print(e)
                sentry.log_error(e)

        return response
