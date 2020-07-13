import decimal
import json

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
from paper.utils import get_cache_key, invalidate_trending_cache
from purchase.models import Purchase, Balance, AggregatePurchase
from purchase.serializers import (
    PurchaseSerializer,
    AggregatePurchaseSerializer
)
from researchhub.settings import ASYNC_SERVICE_HOST
from utils.http import http_request, RequestMethods
from utils.permissions import CreateOrUpdateOrReadOnly
from user.models import User


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, CreateOrUpdateOrReadOnly]
    pagination_class = PageNumberPagination

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
            purchase.group = purchase.group()
            purchase.save()

        if content_type_str == 'paper':
            paper = Paper.objects.get(id=object_id)
            paper.calculate_hot_score()
            cache_key = get_cache_key(None, 'paper', pk=object_id)
            cache.delete(cache_key)
            invalidate_trending_cache([])

        context = {
            'purchase_minimal_serialization': True
        }
        serializer = self.serializer_class(purchase, context=context)
        serializer_data = serializer.data
        return Response(serializer_data, status=201)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        purchase = self.get_object()
        purchase.group = purchase.group()
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
    def user_transactions(self, request, pk=None):
        context = self.get_serializer_context()
        context['purchase_minimal_serialization'] = True

        user = User.objects.get(id=pk)
        queryset = user.purchases.all()

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.serializer_class(
                page,
                context=context,
                many=True
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def temp(self, request, pk=None):
        user = request.user
        context = self.get_serializer_context()
        context['purchase_minimal_serialization'] = True
        groups = AggregatePurchase.objects.filter(user=user)
        serializer = AggregatePurchaseSerializer(
            groups,
            context=context,
            many=True
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def user_transactions_by_item(self, request):
        context = self.get_serializer_context()
        context['purchase_minimal_serialization'] = True
        queryset = Purchase.objects.filter(user=request.user).order_by(
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
