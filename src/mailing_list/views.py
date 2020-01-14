import json
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import (
    action,
    api_view,
    parser_classes,
    permission_classes
)
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import Response

from mailing_list.exceptions import EmailNotificationError
from mailing_list.models import EmailRecipient
from mailing_list.serializers import EmailRecipientSerializer
from utils.http import http_request, RequestMethods
from utils.parsers import PlainTextParser
from utils.sentry import log_info, log_error, log_request_error


class EmailRecipientViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = EmailRecipient.objects.all()
    serializer_class = EmailRecipientSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return EmailRecipient.objects.all()
        else:
            return EmailRecipient.objects.filter(pk=user.id)

    @action(
        detail=False,
        methods=[RequestMethods.POST],
        permission_classes=[AllowAny]
    )
    def update_or_create_email_preference(self, request):
        email = request.data.get('email')
        is_opted_out = request.data.get('opt_out')
        is_subscribed = request.data.get('subscribe')

        email_recipient, created = EmailRecipient.objects.get_or_create(
            email=email
        )

        if email_recipient.is_opted_out != is_opted_out:
            email_recipient.set_opted_out(is_opted_out)
        if email_recipient.is_subscribed != is_subscribed:
            email_recipient.set_subscribed(is_subscribed)

        status = 200
        if created:
            status = 201

        return Response('success', status=status)


@api_view([RequestMethods.POST])
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
                try:
                    recipient, created = EmailRecipient.objects.get_or_create(
                        email=email_address
                    )
                    recipient.bounced()
                except Exception as e:
                    message = (
                        f'Failed handling bounced recipient: {email_address}'
                    )
                    error = EmailNotificationError(e, message)
                    print(error)
                    log_error(error, base_error=e)
    elif data_type == 'Complaint':
        message = (f'`email_notifications` received {data_type}')
        log_info(message)
    else:
        message = (
            f'`email_notifications` received unsupported type {data_type}'
        )
        print(message)

    return Response({})
