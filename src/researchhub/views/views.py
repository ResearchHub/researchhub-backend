from django.http import HttpResponse
from django.template.loader import render_to_string


def index(_):
    return HttpResponse("Authenticate with a token in the Authorization header.")


def robots_txt(_):
    content = render_to_string("robots.txt")
    return HttpResponse(content, content_type="text/plain")
