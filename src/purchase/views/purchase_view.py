import datetime
import decimal
import time

from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from analytics.tasks import track_revenue_event
from notification.models import Notification
from paper.models import Paper
from paper.utils import get_cache_key
from purchase.models import AggregatePurchase, Balance, Purchase
from purchase.related_models.constants.support import (
    MAXIMUM_SUPPORT_AMOUNT_RSC,
    MINIMUM_SUPPORT_AMOUNT_RSC,
)
from purchase.serializers import AggregatePurchaseSerializer, PurchaseSerializer
from purchase.tasks import send_support_email
from purchase.utils import distribute_support_to_authors
from reputation.distributions import create_purchase_distribution
from reputation.distributor import Distributor
from reputation.models import Contribution, SupportFee
from reputation.tasks import create_contribution
from reputation.utils import calculate_support_fees, deduct_support_fees
from researchhub.settings import BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.filters import HOT
from user.models import Action, User
from utils.permissions import CreateOrReadOnly
from utils.throttles import THROTTLE_CLASSES


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, CreateOrReadOnly]
    pagination_class = PageNumberPagination
    throttle_classes = THROTTLE_CLASSES
    ALLOWED_CONTENT_TYPES = ("rhcommentmodel", "paper", "researchhubpost")

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    @track_event
    def create(self, request):
        user = request.user

        data = request.data

        amount = data["amount"]
        purchase_method = data["purchase_method"]
        purchase_type = data["purchase_type"]
        content_type_str = data["content_type"]
        object_id = data["object_id"]
        transfer_rsc = False
        recipient = None

        if user.probable_spammer:
            return Response(
                {
                    "detail": f"Account under review. Please contact support.",
                },
                status=403,
            )

        if content_type_str not in self.ALLOWED_CONTENT_TYPES:
            return Response(status=400)

        if purchase_method not in (Purchase.OFF_CHAIN, Purchase.ON_CHAIN):
            return Response(status=400)

        decimal_amount = decimal.Decimal(amount)
        if decimal_amount <= 0:
            return Response(status=400)

        content_type = ContentType.objects.get(model=content_type_str)
        with transaction.atomic():
            user = User.objects.select_for_update().get(id=user.id)

            purchase_data = {
                "amount": amount,
                "user": user.id,
                "content_type": content_type.id,
                "object_id": object_id,
                "purchase_type": purchase_type,
            }

            if purchase_method == Purchase.ON_CHAIN:
                purchase_data["purchase_method"] = Purchase.ON_CHAIN
            else:
                if (
                    decimal_amount < MINIMUM_SUPPORT_AMOUNT_RSC
                    or decimal_amount > MAXIMUM_SUPPORT_AMOUNT_RSC
                ):
                    return Response(
                        {
                            "detail": f"Invalid amount. Minimum of {MINIMUM_SUPPORT_AMOUNT_RSC} RSC.",
                        },
                        status=400,
                    )

                user_balance = user.get_balance()
                (
                    total_fee,
                    rh_fee,
                    dao_fee,
                    current_support_fee,
                ) = calculate_support_fees(decimal_amount)
                if user_balance - (decimal_amount + total_fee) < 0:
                    return Response("Insufficient Funds", status=402)

                # Deduct fees from the gross amount of the purchase.
                deduct_support_fees(
                    user, total_fee, rh_fee, dao_fee, current_support_fee
                )

                # Create a purchase object with the pre-fees amount
                purchase_data["purchase_method"] = Purchase.OFF_CHAIN
                purchase_data["paid_status"] = Purchase.PAID
                request._full_data = purchase_data
                create_response = super().create(request)
                purchase_id = create_response.data["id"]
                purchase = self.get_queryset().get(id=purchase_id)
                source_type = ContentType.objects.get_for_model(purchase)

                # Create a balance object for the fees and the purchase amount
                fee_str = total_fee.to_eng_string()
                Balance.objects.create(
                    user=user,
                    content_type=ContentType.objects.get_for_model(SupportFee),
                    object_id=current_support_fee.id,
                    amount=f"-{fee_str}",
                )
                Balance.objects.create(
                    user=user,
                    content_type=source_type,
                    object_id=purchase_id,
                    amount=f"-{amount}",
                )

                # Track in Amplitude
                rh_fee_str = rh_fee.to_eng_string()
                track_revenue_event.apply_async(
                    (
                        user.id,
                        "SUPPORT_FEE",
                        rh_fee_str,
                        None,
                        "OFF_CHAIN",
                        content_type.model,
                        object_id,
                    ),
                    priority=1,
                )

            purchase_hash = purchase.hash()
            purchase.purchase_hash = purchase_hash
            purchase_boost_time = purchase.get_boost_time(amount)
            purchase.boost_time = purchase_boost_time
            purchase.group = purchase.get_aggregate_group()
            purchase.save()
            paper = None

            item = purchase.item
            context = {"purchase_minimal_serialization": True, "exclude_stats": True}
            notification_type = Notification.RSC_SUPPORT_ON_DOC

            #  transfer_rsc is set each time just in case we want
            #  to disable rsc transfer for a specific item
            if content_type_str == "paper":
                paper = Paper.objects.get(id=object_id)
                unified_doc = paper.unified_document
                recipient = paper.uploaded_by
                cache_key = get_cache_key("paper", object_id)
                cache.delete(cache_key)
                transfer_rsc = False

                distribute_support_to_authors(paper, purchase, amount)

            elif content_type_str == "rhcommentmodel":
                transfer_rsc = True
                recipient = item.created_by
                unified_doc = item.unified_document
                notification_type = Notification.RSC_SUPPORT_ON_DIS
            elif content_type_str == "researchhubpost":
                transfer_rsc = True
                recipient = item.created_by
                unified_doc = item.unified_document

            if transfer_rsc and recipient and recipient != user:
                distribution = create_purchase_distribution(user, amount)
                distributor = Distributor(
                    distribution, recipient, purchase, time.time(), user
                )
                distributor.distribute()

        serializer = self.serializer_class(purchase, context=context)
        serializer_data = serializer.data

        if recipient and user:
            self.send_purchase_notification(
                purchase, unified_doc, recipient, notification_type
            )
            self.send_purchase_email(purchase, recipient, unified_doc)

        create_contribution.apply_async(
            (
                Contribution.SUPPORTER,
                {"app_label": "purchase", "model": "purchase"},
                user.id,
                unified_doc.id,
                purchase.id,
            ),
            priority=2,
            countdown=10,
        )
        return Response(serializer_data, status=201)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def aggregate_user_promotions(self, request, pk=None):
        user = User.objects.get(id=pk)
        context = self.get_serializer_context()
        context["purchase_minimal_serialization"] = True
        paper_content_type_id = ContentType.objects.get_for_model(Paper).id
        post_content_type_id = ContentType.objects.get_for_model(ResearchhubPost).id
        groups = AggregatePurchase.objects.filter(
            user=user,
            content_type_id__in=[paper_content_type_id, post_content_type_id],
        )

        page = self.paginate_queryset(groups)
        if page is not None:
            serializer = AggregatePurchaseSerializer(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        serializer = AggregatePurchaseSerializer(groups, context=context, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"], permission_classes=[IsAuthenticated])
    def user_promotions(self, request, pk=None):
        context = self.get_serializer_context()
        context["purchase_minimal_serialization"] = True

        user = User.objects.get(id=pk)
        queryset = Purchase.objects.filter(user=user).order_by(
            "-created_date", "object_id"
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.serializer_class(page, many=True, context=context)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def send_purchase_notification(
        self, purchase, unified_doc, recipient, notification_type
    ):
        creator = purchase.user

        if creator == recipient:
            return

        content_type = ContentType.objects.get_for_model(purchase)
        Action.objects.create(
            user=recipient,
            content_type=content_type,
            object_id=purchase.id,
        )
        notification = Notification.objects.create(
            unified_document=unified_doc,
            recipient=recipient,
            action_user=creator,
            item=purchase,
            notification_type=notification_type,
        )
        notification.send_notification()

    def send_purchase_email(self, purchase, recipient, unified_doc):
        sender = purchase.user
        if sender == recipient:
            return

        # TODO: Add email support for posts
        paper_id = None
        try:
            paper = unified_doc.paper
            if not paper:
                return
            else:
                paper_id = paper.id
        except Exception as e:
            print(e)

        sender_balance_date = datetime.datetime.now().strftime("%m/%d/%Y")
        amount = purchase.amount
        payment_type = purchase.purchase_method
        content_type_str = purchase.content_type.model
        object_id = purchase.object_id
        send_support_email.apply_async(
            (
                f"{BASE_FRONTEND_URL}/user/{sender.author_profile.id}/overview",
                sender.full_name(),
                recipient.full_name(),
                recipient.email,
                amount,
                sender_balance_date,
                payment_type,
                "recipient",
                content_type_str,
                object_id,
                paper_id,
            ),
            priority=6,
            countdown=2,
        )

        send_support_email.apply_async(
            (
                f"{BASE_FRONTEND_URL}/user/{recipient.author_profile.id}/overview",
                sender.full_name(),
                recipient.full_name(),
                sender.email,
                amount,
                sender_balance_date,
                payment_type,
                "sender",
                content_type_str,
                object_id,
                paper_id,
            ),
            priority=6,
            countdown=2,
        )
