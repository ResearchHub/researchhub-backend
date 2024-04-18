import os
import time

from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from web3 import Web3

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.models import Deposit
from reputation.serializers import DepositSerializer
from utils.permissions import APIPermission


class DepositViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Deposit.objects.all()
    serializer_class = DepositSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Deposit.objects.all()
        else:
            return Deposit.objects.filter(user=user)

    @action(detail=False, methods=["post"], permission_classes=[APIPermission])
    def deposit_rsc(self, request):
        """
        This is a request to deposit RSC from our researchhub-async-service
        TODO: Add a websocket call here so we can ping the frontend that the transaction completed
        """
        return Response(
            "Deposits are suspended for the time being. Please be patient as we work to turn deposits back on",
            status=400,
        )
        deposit = Deposit.objects.get(id=request.data.get("deposit_id"))
        amt = deposit.amount
        user = deposit.user
        distribution = Dist("DEPOSIT", amt, give_rep=False)
        distributor = Distributor(distribution, user, user, time.time(), user)
        distributor.distribute()
        return Response({"message": "Deposit successful"})

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated],
    )
    def start_deposit_rsc(self, request):
        """
        Create a pending deposit that will be updated by a celery task
        """
        return Response(
            "Deposits are suspended for the time being. Please be patient as we work to turn deposits back on",
            status=400,
        )

        Deposit.objects.create(
            user=request.user,
            amount=request.data.get("amount"),
            from_address=request.data.get("from_address"),
            transaction_hash=request.data.get("transaction_hash"),
        )

        return Response(200)
