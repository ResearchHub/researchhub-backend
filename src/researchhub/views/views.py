import os

from django.http import HttpResponse
from django.template.loader import render_to_string

from researchhub.settings import BASE_DIR


def index(_):
    return HttpResponse("Authenticate with a token in the Authorization header.")


def permissions(_):
    path = os.path.join(BASE_DIR, "static", "researchhub", "user_permissions.json")
    with open(path, "r") as file:
        data = file.read()
    return HttpResponse(content=data, content_type="application/json")


def robots_txt(_):
    content = render_to_string("robots.txt")
    return HttpResponse(content, content_type="text/plain")
