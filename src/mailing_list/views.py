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
from mailing_list.models import (
    DigestSubscription,
    EmailRecipient,
    PaperSubscription,
    ThreadSubscription,
    CommentSubscription,
    ReplySubscription
)
from mailing_list.serializers import EmailRecipientSerializer
from utils.http import http_request, POST, PATCH
from utils.parsers import PlainTextParser
from utils.sentry import log_info, log_error, log_request_error


class EmailRecipientViewSet(viewsets.ModelViewSet):
    serializer_class = EmailRecipientSerializer
    permission_classes = [IsAuthenticated]

    def create(self, *args, **kwargs):
        user = self.request.user

        if user.is_anonymous:
            user = None
            email = self.request.data.get('email')
        else:
            email = user.email

        email_recipient, created = EmailRecipient.objects.get_or_create(
            user=user,
            email=email
        )
        if not created:
            return Response('Already exists', status=400)

        email_recipient.digest_subscription = (
            DigestSubscription.objects.create()
        )
        email_recipient.paper_subscription = PaperSubscription.objects.create()
        email_recipient.thread_subscription = (
            ThreadSubscription.objects.create()
        )
        email_recipient.comment_subscription = (
            CommentSubscription.objects.create()
        )
        email_recipient.reply_subscription = ReplySubscription.objects.create()
        email_recipient.save()

        return Response(
            EmailRecipientSerializer(email_recipient).data,
            status=201
        )

    def destroy(self, *args, **kwargs):
        user = self.request.user
        if user.is_admin:
            return super().destroy()
        else:
            return Response('Unauthorized', status=400)

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return EmailRecipient.objects.all()
        else:
            return EmailRecipient.objects.filter(user=user)

    @action(
        detail=True,
        methods=[PATCH],
        permission_classes=[IsAuthenticated]
    )
    def subscriptions(self, request, pk=None):
        email_recipient = self.get_object()

        is_opted_out = request.data.get('is_opted_out', None)
        if is_opted_out is not None:
            email_recipient.is_opted_out = is_opted_out
            email_recipient.save()

        self._update_subscription(request, 'digest_subscription')
        self._update_subscription(request, 'paper_subscription')
        self._update_subscription(request, 'thread_subscription')
        self._update_subscription(request, 'comment_subscription')
        self._update_subscription(request, 'reply_subscription')

        return Response(
            EmailRecipientSerializer(email_recipient).data,
            status=200
        )

    def _update_subscription(
        self,
        request,
        subscription_name
    ):
        email_recipient = self.get_object()

        data = request.data.get(subscription_name)
        if not data:
            return

        if subscription_name == 'digest_subscription':
            sub_id = email_recipient.digest_subscription.id
            model = DigestSubscription
        elif subscription_name == 'paper_subscription':
            sub_id = email_recipient.paper_subscription.id
            model = PaperSubscription
        elif subscription_name == 'thread_subscription':
            sub_id = email_recipient.thread_subscription.id
            model = ThreadSubscription
        elif subscription_name == 'comment_subscription':
            sub_id = email_recipient.comment_subscription.id
            model = CommentSubscription
        elif subscription_name == 'reply_subscription':
            sub_id = email_recipient.reply_subscription.id
            model = ReplySubscription

        model.objects.update_or_create(
            id=sub_id,
            defaults=data
        )

    @action(
        detail=False,
        methods=[POST],
        permission_classes=[AllowAny]
    )
    def update_or_create_email_preference(self, request):
        """Enables anonymous users to unsubscribe."""

        email = request.data.get('email')

        # TODO: Uncomment to restrict to anonymous users
        # if EmailRecipient.objects.filter(
        #     email=email,
        #     user__isnull=False
        # ).exists():
        #     return Response(
        #         'This route is only for anonymous users',
        #         status=400
        #     )

        email_recipient, created = EmailRecipient.objects.get_or_create(
            email=email
        )

        is_opted_out = request.data.get('opt_out')

        if email_recipient.is_opted_out != is_opted_out:
            email_recipient.set_opted_out(is_opted_out)

        status = 200
        if created:
            status = 201

        return Response('success', status=status)


@api_view([POST])
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
                # TODO: Sanitize email address before putting it in the db
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
