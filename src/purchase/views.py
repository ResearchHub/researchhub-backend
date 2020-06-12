import decimal

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated
)

from rest_framework.response import Response
from purchase.models import Purchase, Balance
from purchase.serializers import PurchaseSerializer
from utils.permissions import CreateOrReadOnly


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated, CreateOrReadOnly]

    def create(self, request):
        user = request.user
        data = request.data

        amount = data['amount']
        purchase_method = data['purchase_method']
        purchase_type = data['purchase_type']
        content_type = data['content_type']
        content_type = ContentType.objects.get(model=content_type)
        object_id = data['object_id']

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
                purchase_hash = purchase.hash()
                purchase.purchase_hash = purchase_hash
                purchase.save()

                source_type = ContentType.objects.get_for_model(purchase)
                Balance.objects.create(
                    user=user,
                    content_type=source_type,
                    object_id=purchase.id,
                    amount=f'-{amount}',
                )

            serializer = self.serializer_class(purchase)
            serializer_data = serializer.data
            return Response(serializer_data, status=201)

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[IsAuthenticated]
    )
    def user_transactions(self, request):
        user = request.user
        transactions = user.purchases
        serializer = self.serializer_class(transactions, many=True)
        serializer_data = serializer.data
        return Response(serializer_data, status=200)
