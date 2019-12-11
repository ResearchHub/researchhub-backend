import json
import os
from researchhub.settings import BASE_DIR
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes
)
from rest_framework.response import Response

from user.models import EmailPreference
from utils.http import http_request
from utils.parsers import PlainTextParser
from utils.sentry import log_info, log_request_error

from rest_framework.exceptions import ParseError


def index(request):
    return HttpResponse(
        "Authenticate with a token in the Authorization header."
    )


@api_view(['POST'])
@permission_classes(())  # Override default permission classes
@parser_classes([PlainTextParser])
@csrf_exempt
def email_notifications(request):
    """Handles AWS SNS email notifications."""

    data = request.data
    if type(request.data) is not dict:
        data = json.loads(request.data)

    data_type = None
    try:
        data_type = data['Type']
    except KeyError:
        raise ParseError(f'Did not find key `Type` in {data}')

    if data_type == 'SubscriptionConfirmation':
        url = data['SubscribeURL']
        resp = http_request('GET', url)
        if resp.status_code != 200:
            message = 'Failed to subscribe to SNS'
            log_request_error(resp, message)

    elif data_type == 'Notification':
        data_message = json.loads(data['Message'])
        if data_message['notificationType'] == 'Bounce':
            bounced_recipients = data_message['bounce']['bouncedRecipients']
            for b_r in bounced_recipients:
                email_address = b_r['emailAddress']
                preference, created = EmailPreference.objects.get_or_create(
                    email=email_address
                )
                preference.bounced = True
                preference.save()
            print(bounced_recipients)

    elif data_type == 'Complaint':
        print('complaint')
    else:
        message = (
            f'`email_notifications` received unsupported type {data_type}'
        )
        print(message)
        log_info(message)

    return Response({})


def permissions(request):
    path = os.path.join(
        BASE_DIR,
        'static',
        'researchhub',
        'user_permissions.json'
    )
    with open(path, 'r') as file:
        data = file.read()
    return HttpResponse(content=data, content_type='application/json')


@api_view(['GET'])
@permission_classes(())
def healthcheck(request):
    """
    Health check for elastic beanstalk
    """

    return Response({'PONG'})
