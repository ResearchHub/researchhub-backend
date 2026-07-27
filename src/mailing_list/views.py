import json
import logging

import requests
from django.views.decorators.csrf import csrf_exempt
from rest_framework import viewsets
from rest_framework.decorators import (
    action,
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import Response

from mailing_list.models import EmailRecipient
from mailing_list.serializers import EmailRecipientSerializer
from utils.parsers import PlainTextParser

logger = logging.getLogger(__name__)


class EmailRecipientViewSet(viewsets.ModelViewSet):
    serializer_class = EmailRecipientSerializer
    permission_classes = [IsAuthenticated]

    def create(self, *args, **kwargs):
        user = self.request.user

        if user.is_anonymous:
            user = None
            email = self.request.data.get("email")
        else:
            email = user.email

        email_recipient, created = EmailRecipient.objects.get_or_create(
            user=user, email=email
        )
        if not created:
            return Response("Already exists", status=400)

        return Response(EmailRecipientSerializer(email_recipient).data, status=201)

    def destroy(self, *args, **kwargs):
        user = self.request.user
        if user.is_admin:
            return super().destroy()
        else:
            return Response("Unauthorized", status=400)

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return EmailRecipient.objects.all()
        else:
            return EmailRecipient.objects.filter(user=user)

    @action(detail=True, methods=["PATCH"], permission_classes=[IsAuthenticated])
    def subscriptions(self, request, pk=None):
        email_recipient = self.get_object()

        is_opted_out = request.data.get("is_opted_out", None)
        if is_opted_out is not None:
            email_recipient.is_opted_out = is_opted_out
            email_recipient.save()

        return Response(EmailRecipientSerializer(email_recipient).data, status=200)

    @action(detail=False, methods=["POST"], permission_classes=[AllowAny])
    def update_or_create_email_preference(self, request):
        """Enables anonymous users to unsubscribe."""

        email = request.data.get("email")
        email_recipient, created = EmailRecipient.objects.get_or_create(email=email)

        is_opted_out = request.data.get("opt_out")

        if email_recipient.is_opted_out != is_opted_out:
            email_recipient.set_opted_out(is_opted_out)

        status = 200
        if created:
            status = 201

        return Response("success", status=status)


@api_view(["POST"])
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
        data_type = data["Type"]
    except KeyError:
        raise ParseError(f"Did not find key `Type` in {data}")

    if data_type == "SubscriptionConfirmation":
        url = data["SubscribeURL"]
        resp = requests.get(url, timeout=30)
        if resp.status_code != 200:
            logger.exception("Failed to subscribe to SNS. Response: %s", resp.text)

    elif data_type == "Notification":
        data_message = json.loads(data["Message"])
        notification_type = data_message["notificationType"]

        if notification_type == "Bounce":
            bounced_recipients = data_message["bounce"]["bouncedRecipients"]
            for b_r in bounced_recipients:
                email_address = b_r["emailAddress"]
                # TODO: Sanitize email address before putting it in the db
                try:
                    recipient, created = EmailRecipient.objects.get_or_create(
                        email=email_address
                    )
                    recipient.bounced()
                except Exception:
                    logger.exception(
                        "Failed handling bounced recipient: %s", email_address
                    )

        elif notification_type == "Complaint":
            complained_recipients = data_message.get("complaint", {}).get(
                "complainedRecipients", []
            )
            for c_r in complained_recipients:
                email_address = c_r["emailAddress"]
                try:
                    recipient, created = EmailRecipient.objects.get_or_create(
                        email=email_address
                    )
                    recipient.do_not_email = True
                    recipient.save(update_fields=["do_not_email"])
                except Exception:
                    logger.exception(
                        "Failed handling complained recipient: %s", email_address
                    )

    else:
        logger.warning("Received unsupported notification type: %s", data_type)

    return Response({})
