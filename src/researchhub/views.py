from django.http import HttpResponse


def index(request):
    return HttpResponse(
        "Authenticate with a token in the Authorization header."
    )
