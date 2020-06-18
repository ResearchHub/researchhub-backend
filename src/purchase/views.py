import decimal

from django.core.cache import cache
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import (
    IsAuthenticated
)

from rest_framework.response import Response
from paper.utils import get_cache_key
from purchase.models import Purchase, Balance
from purchase.serializers import PurchaseSerializer
from utils.permissions import CreateOrUpdateOrReadOnly


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

                with transaction.atomic():
                    purchase = Purchase.objects.create(
                        user=user,
                        content_type=content_type,
                        object_id=object_id,
                        purchase_method=purchase_method,
                        purchase_type=purchase_type,
                        amount=amount
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
                purchase.save()

        if content_type_str == 'paper':
            cache_key = get_cache_key(None, 'paper', pk=object_id)
            cache.delete(cache_key)

        context = {
            'purchase_minimal_serialization': True
        }
        serializer = self.serializer_class(purchase, context=context)
        serializer_data = serializer.data
        return Response(serializer_data, status=201)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def user_transactions(self, request):
        context = {
            'purchase_minimal_serialization': True
        }
        user = request.user
        transactions = user.purchases.all()
        page = self.paginate_queryset(transactions)
        if page is not None:
            serializer = self.serializer_class(
                page,
                context=context,
                many=True
            )
            return self.get_paginated_response(serializer.data)
