from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string


def index(_):
    return JsonResponse({"message": "Welcome to the ResearchHub API"})


def robots_txt(_):
    content = render_to_string("robots.txt")
    return HttpResponse(content, content_type="text/plain")
