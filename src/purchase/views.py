import datetime
import decimal
import json
import time

import stripe
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from analytics.amplitude import track_event
from notification.models import Notification
from paper.models import Paper
from paper.utils import get_cache_key
from purchase.models import (
    AggregatePurchase,
    Balance,
    Purchase,
    RscExchangeRate,
    Support,
    Wallet,
)
from purchase.permissions import CanSendRSC
from purchase.serializers import (
    AggregatePurchaseSerializer,
    BalanceSerializer,
    PurchaseSerializer,
    RscExchangeRateSerializer,
    SupportSerializer,
    WalletSerializer,
)
from purchase.tasks import send_support_email
from purchase.utils import distribute_support_to_authors
from reputation.distributions import Distribution, create_purchase_distribution
from reputation.distributor import Distributor
from reputation.models import Contribution, Escrow
from reputation.tasks import create_contribution
from researchhub.settings import ASYNC_SERVICE_HOST, BASE_FRONTEND_URL
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.filters import HOT
from researchhub_document.utils import reset_unified_document_cache
from user.models import Action, Author, User
from user.permissions import IsModerator
from user.serializers import UserSerializer
from utils.http import RequestMethods, http_request
from utils.permissions import (
    CreateOrReadOnly,
    CreateOrUpdateIfAllowed,
    CreateOrUpdateOrReadOnly,
)
from utils.throttles import THROTTLE_CLASSES


class BalanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    permission_classes = [
        IsAuthenticated,
    ]
    pagination_class = PageNumberPagination
    throttle_classes = THROTTLE_CLASSES

    def get_queryset(self):
        user = self.request.user
        return self.queryset.filter(user=user).order_by("-created_date")

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[IsAuthenticated, IsModerator, CanSendRSC],
    )
    def send_rsc(self, request):
        recipient_id = request.data.get("recipient_id", "")
        amount = request.data.get("amount", 0)
        if recipient_id:
            user = request.user
            user_id = user.id
            content_type = ContentType.objects.get(model="distribution")
            proof_content_type = ContentType.objects.get(model="user")
            proof = {
                "table": "user_user",
                "record": {
                    "id": user_id,
                    "email": user.email,
                    "name": user.first_name + " " + user.last_name,
                },
            }
            distribution = Distribution("MOD_PAYOUT", amount, give_rep=False)
            timestamp = time.time()
            user_proof = User.objects.get(id=recipient_id)
            distributor = Distributor(
                distribution, user_proof, user_proof, timestamp, user
            )

            distributor.distribute()

        return Response({"message": "RSC Sent!"})


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, CreateOrReadOnly]
    pagination_class = PageNumberPagination
    throttle_classes = THROTTLE_CLASSES
    ALLOWED_CONTENT_TYPES = ("rhcommentmodel", "paper", "researchhubpost")

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

        if content_type_str not in self.ALLOWED_CONTENT_TYPES:
            return Response(status=400)

        if purchase_method not in (Purchase.OFF_CHAIN, Purchase.ON_CHAIN):
            return Response(status=400)

        decimal_amount = decimal.Decimal(amount)
        if decimal_amount <= 0:
            return Response(status=400)

        content_type = ContentType.objects.get(model=content_type_str)
        with transaction.atomic():
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
                user_balance = user.get_balance()
                if user_balance - decimal_amount < 0:
                    return Response("Insufficient Funds", status=402)

                purchase_data["purchase_method"] = Purchase.OFF_CHAIN
                purchase_data["paid_status"] = Purchase.PAID
                request._full_data = purchase_data
                create_response = super().create(request)
                purchase_id = create_response.data["id"]
                purchase = self.get_queryset().get(id=purchase_id)
                source_type = ContentType.objects.get_for_model(purchase)
                Balance.objects.create(
                    user=user,
                    content_type=source_type,
                    object_id=purchase_id,
                    amount=f"-{amount}",
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
                paper.calculate_hot_score()
                recipient = paper.uploaded_by
                cache_key = get_cache_key("paper", object_id)
                cache.delete(cache_key)
                transfer_rsc = False

                distribute_support_to_authors(paper, purchase, amount)

                hub_ids = paper.hubs.values_list("id", flat=True)
                reset_unified_document_cache(
                    hub_ids,
                    document_type=["all", "paper"],
                    filters=[HOT],
                )
            elif content_type_str == "rhcommentmodel":
                transfer_rsc = True
                recipient = item.created_by
                unified_doc = item.unified_document
                notification_type = Notification.RSC_SUPPORT_ON_DIS
            elif content_type_str == "researchhubpost":
                transfer_rsc = True
                recipient = item.created_by
                unified_doc = item.unified_document

                hub_ids = unified_doc.hubs.values_list("id", flat=True)
                reset_unified_document_cache(
                    hub_ids,
                    document_type=["all", "posts"],
                    filters=[HOT],
                )

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

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        purchase = self.get_object()
        purchase.group = purchase.get_aggregate_group()
        purchase.save()

        if purchase.transaction_hash:
            self.track_paid_status(purchase.id, purchase.transaction_hash)
        return response

    def track_paid_status(self, purchase_id, transaction_hash):
        url = ASYNC_SERVICE_HOST + "/ethereum/track_purchase"
        data = {"purchase": purchase_id, "transaction_hash": transaction_hash}
        response = http_request(
            RequestMethods.POST, url, data=json.dumps(data), timeout=3
        )
        response.raise_for_status()
        return response

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


class RscExchangeRatePagination(PageNumberPagination):
    page_size_query_param = "page_size"
    max_page_size = 10


class RscExchangeRateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RscExchangeRate.objects.all()
    serializer_class = RscExchangeRateSerializer
    permission_classes = [AllowAny]
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    pagination_class = RscExchangeRatePagination
    filterset_fields = [
        "price_source",
    ]


class StripeViewSet(viewsets.ModelViewSet):
    # Deprecated
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = []
    throttle_classes = []

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def onboard_stripe_account(self, request):
        user = request.user
        wallet = user.author_profile.wallet

        if not wallet.stripe_acc or not wallet.stripe_verified:
            acc = stripe.Account.create(
                type="express",
                country="US",  # This is where our business resides
                email=user.email,
                capabilities={
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            )

            wallet.stripe_acc = acc["id"]
            wallet.save()
        elif wallet:
            account_links = stripe.Account.create_login_link(wallet.stripe_acc)
            return Response(account_links, status=200)

        refresh_url = request.data["refresh_url"]
        return_url = request.data["return_url"]

        try:
            account_links = stripe.AccountLink.create(
                account=wallet.stripe_acc,
                refresh_url=refresh_url,
                return_url=return_url,
                type="account_onboarding",
            )
        except Exception as e:
            return Response(e, status=400)
        return Response(account_links, status=200)

    @action(detail=True, methods=["get"])
    def verify_stripe_account(self, request, pk=None):
        author = Author.objects.get(id=pk)
        wallet = author.wallet
        stripe_id = wallet.stripe_acc
        acc = stripe.Account.retrieve(stripe_id)

        redirect = f"{BASE_FRONTEND_URL}/user/{pk}/stripe?verify_stripe=true"
        account_links = stripe.Account.create_login_link(
            stripe_id, redirect_url=redirect
        )

        if acc["charges_enabled"]:
            wallet.stripe_verified = True
            wallet.save()
            return Response({**account_links}, status=200)

        return Response(
            {
                "reason": "Please complete verification via Stripe Dashboard",
                **account_links,
            },
            status=200,
        )

    @action(detail=False, methods=["post"])
    def stripe_capability_updated(self, request):
        data = request.data
        acc_id = data["account"]
        acc_obj = data["data"]["object"]
        status = acc_obj["status"]
        capability_type = acc_obj["id"]
        requirements = acc_obj["requirements"]
        currently_due = requirements["currently_due"]

        id_due = "individual.id_number" in currently_due
        id_verf_due = "individual.verification.document" in currently_due

        if capability_type != "transfers" or status == "pending":
            return Response(status=200)

        wallet = self.queryset.get(stripe_acc=acc_id)
        user = wallet.author.user
        if status == "active" and not wallet.stripe_verified:
            account_links = stripe.Account.create_login_link(acc_id)
            wallet.stripe_verified = True
            wallet.save()
            self._send_stripe_notification(
                user, status, "Your Stripe account has been verified", **account_links
            )
        elif status == "active" and wallet.stripe_verified:
            return Response(status=200)

        if not id_due and not id_verf_due and not len(currently_due) <= 2:
            return Response(status=200)

        try:
            account_links = stripe.Account.create_login_link(acc_id)
        except Exception as e:
            return Response(e, status=200)

        message = ""
        if id_due:
            message = """
                Social Security Number or other
                government identification
            """
        elif id_verf_due:
            message = """
                Documents pertaining to government
                identification
            """

        self._send_stripe_notification(user, status, message, **account_links)
        return Response(status=200)

    def _send_stripe_notification(self, user, status, message, **kwargs):
        user_id = user.id
        user_type = ContentType.objects.get(model="user")
        action = Action.objects.create(
            user=user,
            content_type=user_type,
            object_id=user_id,
        )
        notification = Notification.objects.create(
            recipient=user,
            action_user=user,
            action=action,
        )

        notification.send_notification()
