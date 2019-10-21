from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

def index(request):
    return HttpResponse(
        "Authenticate with a token in the Authorization header."
    )


@api_view(['GET'])
@permission_classes(())
def healthcheck(request):
    """
    Health check for elastic beanstalk
    """

    return Response({'PONG'})
