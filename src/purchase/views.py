from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated
)

from rest_framework.response import Response

from purchase.models import Purchase
from purchase.serializers import PurchaseSerializer


class PurchaseViewSet(viewsets.ModelViewSet):
    queryset = Purchase.objects.all()
    serializer_class = PurchaseSerializer
    permission_classes = [IsAuthenticated]

    @action(
        detail=False,
        methods=['post'],
        permission_classes=[IsAuthenticated]
    )
    def off_chain_purchase(self, request):
        user = request.user
        data = request.data
        amount = float(data['amount'])
        content_type = data['content_type']
        object_id = data['object_id']
        user_balance = user.reputation

        if user_balance - amount < 0:
            return Response('Insufficient Funds', status=402)

        with transaction.atomic():
            user.reputation = user_balance - amount
            purchase = Purchase.objects.create(
                user=user,
                content_type_id=content_type,
                object_id=object_id,
                purchase_type=Purchase.OFF_CHAIN,
                amount=amount
            )
            user.save()

        serializer = self.serializer_class(purchase)
        serializer_data = serializer.data
        return Response({'data': serializer_data})

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
        return Response({'data': serializer_data})
