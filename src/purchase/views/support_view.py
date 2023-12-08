import datetime
import decimal

import stripe
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from purchase.models import (
    Balance,
    Support,
)
from purchase.serializers import (
    SupportSerializer,
)
from purchase.tasks import send_support_email
from researchhub.settings import BASE_FRONTEND_URL
from user.models import Author, User
from user.serializers import UserSerializer
from utils.permissions import (
    CreateOrUpdateIfAllowed,
    CreateOrUpdateOrReadOnly,
)
from utils.throttles import THROTTLE_CLASSES


class SupportViewSet(viewsets.ModelViewSet):
    queryset = Support.objects.all()
    serializer_class = SupportSerializer
    permission_classes = [
        IsAuthenticated,
        CreateOrUpdateOrReadOnly,
        CreateOrUpdateIfAllowed,
    ]
    throttle_classes = THROTTLE_CLASSES

    @action(
        detail=False, methods=["get"], permission_classes=[CreateOrUpdateOrReadOnly]
    )
    def get_supported(self, request):
        paper_id = request.query_params.get("paper_id")
        author_id = request.query_params.get("author_id")

        if paper_id:
            paper_type = ContentType.objects.get(model="paper")
            supports = self.queryset.filter(content_type=paper_type, object_id=paper_id)
        elif author_id:
            author_type = ContentType.objects.get(model="author")
            supports = self.queryset.filter(
                content_type=author_type, object_id=author_id
            )
        else:
            return Response({"message": "No query param included"}, status=400)

        user_ids = supports.values_list("sender", flat=True)
        users = User.objects.filter(id__in=user_ids, is_suspended=False)
        page = self.paginate_queryset(users)
        if page is not None:
            serializer = UserSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        return Response({"message": "Error"}, status=400)

    @track_event
    def create(self, request):
        sender = request.user
        data = request.data
        payment_option = data["payment_option"]
        payment_type = data["payment_type"]
        sender_id = data["user_id"]
        recipient_id = data["recipient_id"]
        recipient = Author.objects.get(id=recipient_id)
        recipient_user = recipient.user
        amount = data["amount"]
        content_type_str = data["content_type"]
        content_type = ContentType.objects.get(model=content_type_str)
        object_id = data["object_id"]

        # User check
        if sender.id != sender_id:
            return Response(status=400)

        # Balance check
        if payment_type == Support.RSC_OFF_CHAIN:
            sender_balance = sender.get_balance()
            decimal_amount = decimal.Decimal(amount)
            if sender_balance - decimal_amount < 0:
                return Response("Insufficient Funds", status=402)

        with transaction.atomic():
            support = Support.objects.create(
                payment_type=payment_type,
                duration=payment_option,
                amount=amount,
                content_type=content_type,
                object_id=object_id,
                sender=sender,
                recipient=recipient_user,
            )
            source_type = ContentType.objects.get_for_model(support)

            if payment_type == Support.RSC_OFF_CHAIN:
                # Subtracting balance from user
                sender_bal = Balance.objects.create(
                    user=sender,
                    content_type=source_type,
                    object_id=support.id,
                    amount=f"-{amount}",
                )

                # Adding balance to recipient
                recipient_bal = Balance.objects.create(
                    user=recipient_user,
                    content_type=source_type,
                    object_id=support.id,
                    amount=amount,
                )

                sender_balance_date = sender_bal.created_date.strftime("%m/%d/%Y")
                recipient_balance_date = recipient_bal.created_date.strftime("%m/%d/%Y")
            elif payment_type == Support.STRIPE:
                recipient_stripe_acc = recipient.wallet.stripe_acc
                if not recipient_stripe_acc:
                    return Response(
                        "Author has not created a Stripe Account", status=403
                    )

                payment_intent = stripe.PaymentIntent.create(
                    payment_method_types=["card"],
                    amount=amount * 100,  # The amount in cents
                    currency="usd",
                    application_fee_amount=0,
                    transfer_data={"destination": recipient_stripe_acc},
                )
                support.proof = payment_intent
                support.save()
                data["client_secret"] = payment_intent["client_secret"]
                sender_balance_date = datetime.datetime.now().strftime("%m/%d/%Y")
                recipient_balance_date = datetime.datetime.now().strftime("%m/%d/%Y")

        send_support_email.apply_async(
            (
                f"{BASE_FRONTEND_URL}/user/{recipient.id}/overview",
                sender.full_name(),
                recipient_user.full_name(),
                sender.email,
                amount,
                sender_balance_date,
                payment_type,
                "sender",
                content_type_str,
                object_id,
            ),
            priority=6,
            countdown=2,
        )

        send_support_email.apply_async(
            (
                f"{BASE_FRONTEND_URL}/user/{sender.author_profile.id}/overview",
                sender.full_name(),
                recipient_user.full_name(),
                recipient_user.email,
                amount,
                recipient_balance_date,
                payment_type,
                "recipient",
                content_type_str,
                object_id,
            ),
            priority=6,
            countdown=2,
        )
        sender_data = UserSerializer(sender).data
        response_data = {"user": sender_data, **data}
        return Response(response_data, status=200)
