import stripe
import decimal
import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.permissions import (
    IsAuthenticated
)

from paper.models import Paper
from paper.utils import (
    get_cache_key,
    invalidate_trending_cache,
    invalidate_top_rated_cache,
    invalidate_newest_cache,
    invalidate_most_discussed_cache,
)
from purchase.models import (
    Purchase,
    Balance,
    AggregatePurchase,
    Wallet,
    Support
)

from purchase.serializers import (
    PurchaseSerializer,
    AggregatePurchaseSerializer,
    WalletSerializer,
    SupportSerializer
)
from notification.models import Notification
from purchase.tasks import send_support_email
from utils.throttles import THROTTLE_CLASSES
from utils.http import http_request, RequestMethods
from utils.permissions import CreateOrUpdateOrReadOnly, CreateOrUpdateIfAllowed
from user.models import User, Author, Action
from user.serializers import UserSerializer

from researchhub.settings import ASYNC_SERVICE_HOST, BASE_FRONTEND_URL


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [
        IsAuthenticated,
        CreateOrUpdateOrReadOnly,
        CreateOrUpdateIfAllowed
    ]
    pagination_class = PageNumberPagination
    throttle_classes = THROTTLE_CLASSES

    def create(self, request):
        user = request.user
        data = request.data

        amount = data['amount']
        purchase_method = data['purchase_method']
        purchase_type = data['purchase_type']
        content_type_str = data['content_type']
        content_type = ContentType.objects.get(model=content_type_str)
        object_id = data['object_id']

        with transaction.atomic():
            if purchase_method == Purchase.ON_CHAIN:
                purchase = Purchase.objects.create(
                    user=user,
                    content_type=content_type,
                    object_id=object_id,
                    purchase_method=purchase_method,
                    purchase_type=purchase_type,
                    amount=amount
                )
            else:
                user_balance = user.get_balance()
                decimal_amount = decimal.Decimal(amount)

                if user_balance - decimal_amount < 0:
                    return Response('Insufficient Funds', status=402)

                purchase = Purchase.objects.create(
                    user=user,
                    content_type=content_type,
                    object_id=object_id,
                    purchase_method=purchase_method,
                    purchase_type=purchase_type,
                    amount=amount,
                    paid_status=Purchase.PAID
                )

                source_type = ContentType.objects.get_for_model(purchase)
                Balance.objects.create(
                    user=user,
                    content_type=source_type,
                    object_id=purchase.id,
                    amount=f'-{amount}',
                )

            purchase_hash = purchase.hash()
            purchase.purchase_hash = purchase_hash
            purchase_boost_time = purchase.get_boost_time(amount)
            purchase.boost_time = purchase_boost_time
            purchase.group = purchase.get_aggregate_group()
            purchase.save()

        if content_type_str == 'paper':
            paper = Paper.objects.get(id=object_id)
            paper.calculate_hot_score()
            cache_key = get_cache_key(None, 'paper', pk=object_id)
            cache.delete(cache_key)
            invalidate_trending_cache([])
            invalidate_top_rated_cache([])
            invalidate_most_discussed_cache([])
            invalidate_newest_cache([])

        context = {
            'purchase_minimal_serialization': True
        }
        serializer = self.serializer_class(purchase, context=context)
        serializer_data = serializer.data
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
        url = ASYNC_SERVICE_HOST + '/ethereum/track_purchase'
        data = {
            'purchase': purchase_id,
            'transaction_hash': transaction_hash
        }
        response = http_request(
            RequestMethods.POST,
            url,
            data=json.dumps(data),
            timeout=3
        )
        response.raise_for_status()
        return response

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def aggregate_user_promotions(self, request, pk=None):
        user = User.objects.get(id=pk)
        context = self.get_serializer_context()
        context['purchase_minimal_serialization'] = True
        groups = AggregatePurchase.objects.filter(user=user)

        page = self.paginate_queryset(groups)
        if page is not None:
            serializer = AggregatePurchaseSerializer(
                page,
                many=True,
                context=context
            )
            return self.get_paginated_response(serializer.data)

        serializer = AggregatePurchaseSerializer(
            groups,
            context=context,
            many=True
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def user_promotions(self, request, pk=None):
        context = self.get_serializer_context()
        context['purchase_minimal_serialization'] = True

        user = User.objects.get(id=pk)
        queryset = Purchase.objects.filter(user=user).order_by(
            '-created_date',
            'object_id'
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.serializer_class(
                page,
                many=True,
                context=context
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class SupportViewSet(viewsets.ModelViewSet):
    queryset = Support.objects.all()
    serializer_class = SupportSerializer
    permission_classes = [
        IsAuthenticated,
        CreateOrUpdateOrReadOnly,
        CreateOrUpdateIfAllowed
    ]
    throttle_classes = THROTTLE_CLASSES

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[CreateOrUpdateOrReadOnly]
    )
    def get_supported(self, request):
        paper_id = request.query_params.get('paper_id')
        author_id = request.query_params.get('author_id')

        if paper_id:
            paper_type = ContentType.objects.get(model='paper')
            supports = self.queryset.filter(
                content_type=paper_type,
                object_id=paper_id
            )
        elif author_id:
            author_type = ContentType.objects.get(model='author')
            supports = self.queryset.filter(
                content_type=author_type,
                object_id=author_id
            )
        else:
            return Response({'message': 'No query param included'}, status=400)

        user_ids = supports.values_list('sender', flat=True)
        users = User.objects.filter(id__in=user_ids)
        page = self.paginate_queryset(users)
        if page is not None:
            serializer = UserSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        return Response({'message': 'Error'}, status=400)

    def create(self, request):
        sender = request.user
        data = request.data
        payment_option = data['payment_option']
        payment_type = data['payment_type']
        sender_id = data['user_id']
        recipient_id = data['recipient_id']
        recipient = Author.objects.get(id=recipient_id)
        recipient_user = recipient.user
        amount = data['amount']
        content_type_str = data['content_type']
        content_type = ContentType.objects.get(model=content_type_str)
        object_id = data['object_id']

        # User check
        if sender.id != sender_id:
            return Response(status=400)

        # Balance check
        if payment_type == Support.RSC_OFF_CHAIN:
            sender_balance = sender.get_balance()
            decimal_amount = decimal.Decimal(amount)
            if sender_balance - decimal_amount < 0:
                return Response('Insufficient Funds', status=402)

        with transaction.atomic():
            support = Support.objects.create(
                payment_type=payment_type,
                duration=payment_option,
                amount=amount,
                content_type=content_type,
                object_id=object_id,
                sender=sender,
                recipient=recipient_user
            )
            source_type = ContentType.objects.get_for_model(support)

            if payment_type == Support.RSC_OFF_CHAIN or payment_type == Support.STRIPE:
                paper_data = {}
                if content_type_str == 'paper':
                    paper = Paper.objects.get(id=object_id)
                    paper_data['title'] = paper.title
                    paper_summary = f'From Paper: {paper.summary}' if paper.summary else ''
                    paper_data['summary'] = paper_summary
                    paper_data['uploaded_by'] = paper.uploaded_by.full_name()
                    paper_data['discussion_count'] = paper.discussion_count
                    paper_data['paper_type'] = ''.join(paper.paper_type.split('_')).capitalize()
                    paper_data['url'] = f'{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}'

                # Subtracting balance from user
                sender_bal = Balance.objects.create(
                    user=sender,
                    content_type=source_type,
                    object_id=support.id,
                    amount=f'-{amount}',
                )
                send_support_email.apply_async(
                    (
                        f'{BASE_FRONTEND_URL}/user/{recipient_user.author_profile.id}/overview',
                        sender.full_name(),
                        recipient_user.full_name(),
                        sender.email,
                        amount,
                        sender_bal.created_date.strftime('%m/%d/%Y'),
                        payment_type,
                        'sender',
                        paper_data
                    ),
                    priority=6,
                    countdown=2
                )

                # Adding balance to recipient
                recipient_bal = Balance.objects.create(
                    user=recipient_user,
                    content_type=source_type,
                    object_id=support.id,
                    amount=amount,
                )

                send_support_email.apply_async(
                    (
                        f'{BASE_FRONTEND_URL}/user/{sender.author_profile.id}/overview',
                        sender.full_name(),
                        recipient_user.full_name(),
                        recipient_user.email,
                        amount,
                        recipient_bal.created_date.strftime('%m/%d/%Y'),
                        payment_type,
                        'recipient',
                        paper_data
                    ),
                    priority=6,
                    countdown=2,
                )
            elif payment_type == Support.STRIPE:
                recipient_stripe_acc = recipient.wallet.stripe_acc
                if not recipient_stripe_acc:
                    return Response(
                        'Author has not created a Stripe Account',
                        status=403
                    )

                payment_intent = stripe.PaymentIntent.create(
                    payment_method_types=['card'],
                    amount=amount * 100,  # The amount in cents
                    currency='usd',
                    application_fee_amount=0,
                    transfer_data={
                        'destination': recipient_stripe_acc
                    }
                )
                support.proof = payment_intent
                support.save()
                data['client_secret'] = payment_intent['client_secret']

        sender_data = UserSerializer(sender).data
        response_data = {'user': sender_data, **data}
        return Response(response_data, status=200)


class StripeViewSet(viewsets.ModelViewSet):
    queryset = Wallet.objects.all()
    serializer_class = WalletSerializer
    permission_classes = []
    throttle_classes = []

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated]
    )
    def onboard_stripe_account(self, request):
        user = request.user
        wallet = user.author_profile.wallet

        if not wallet.stripe_acc or not wallet.stripe_verified:
            acc = stripe.Account.create(
                type='express',
                country='US',  # This is where our business resides
                email=user.email,
                capabilities={
                    'card_payments': {'requested': True},
                    'transfers': {'requested': True},
                },
            )

            wallet.stripe_acc = acc['id']
            wallet.save()
        elif wallet:
            account_links = stripe.Account.create_login_link(wallet.stripe_acc)
            return Response(account_links, status=200)

        refresh_url = request.data['refresh_url']
        return_url = request.data['return_url']

        try:
            account_links = stripe.AccountLink.create(
                account=wallet.stripe_acc,
                refresh_url=refresh_url,
                return_url=return_url,
                type='account_onboarding'
            )
        except Exception as e:
            return Response(e, status=400)
        return Response(account_links, status=200)

    @action(
        detail=True,
        methods=['get']
    )
    def verify_stripe_account(self, request, pk=None):
        author = Author.objects.get(id=pk)
        wallet = author.wallet
        stripe_id = wallet.stripe_acc
        acc = stripe.Account.retrieve(stripe_id)

        if acc['charges_enabled']:
            wallet.stripe_verified = True
            wallet.save()
            return Response(True, status=200)

        redirect = f'{BASE_FRONTEND_URL}/user/{pk}/stripe?verify_stripe=true'
        account_links = stripe.Account.create_login_link(
            stripe_id,
            redirect_url=redirect
        )
        return Response(
            {
                'reason': 'Please complete verification via Stripe Dashboard',
                **account_links
            },
            status=200
        )

    @action(detail=False, methods=['post'])
    def stripe_account_updated(self, request):
        data = request.data
        acc_id = data['account']
        acc_obj = data['data']['object']
        charges_enabled = acc_obj['charges_enabled']
        wallet = self.queryset.get(stripe_acc=acc_id)
        user = wallet.author.user

        if charges_enabled:
            wallet.stripe_verified = charges_enabled
            wallet.save()
            message = 'Your Stripe Account has been verified'
            self._send_stripe_notification(user, 'verified', message)
            return Response(status=200)

        requirements = acc_obj['requirements']
        reason = requirements['disabled_reason']

        if reason == 'requirements.pending_verification':
            message = 'Your Stripe Account is pending verification'
            self._send_stripe_notification(user, 'pending', message)
        else:
            errors = requirements['errors']
            message = ''
            for error in errors:
                error_reason = error['reason']
                message += f'{error_reason}\n'
            account_links = stripe.Account.create_login_link(acc_id)
            self._send_stripe_notification(
                user,
                'incomplete',
                message,
                **account_links
            )

        return Response(status=200)

    def _send_stripe_notification(self, user, status, message, **kwargs):
        user_id = user.id
        user_type = ContentType.objects.get(model='user')
        action = Action.objects.create(
            user=user,
            content_type=user_type,
            object_id=user_id,
        )
        notification = Notification.objects.create(
            recipient=user,
            action_user=user,
            action=action,
            extra={
                'status': status,
                'message': message,
                **kwargs
            }
        )

        notification.send_notification()
