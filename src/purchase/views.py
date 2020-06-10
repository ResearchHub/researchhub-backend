from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import (
    IsAuthenticated
)

from rest_framework.response import Response
from reputation.distributions import DISTRIBUTION_TYPE_CHOICES
from reputation.models import Distribution
from reputation.lib import get_user_balance
from purchase.models import Purchase
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
        content_type = ContentType(model=content_type)
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
            # TODO: amount conversion stuff
            user_balance = get_user_balance(user)

            if user_balance - amount < 0:
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

                purchase_distribution = DISTRIBUTION_TYPE_CHOICES.Purchase(
                    'PURCHASE',
                    -amount
                )
                Distribution.objects.create(
                    recipient=user,
                    amount=amount,
                    distribution_type=purchase_distribution,
                    proof_item_content_type=content_type,
                    proof_item_object_id=object_id,
                    distributed_status=Distribution.DISTRIBUTED
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
