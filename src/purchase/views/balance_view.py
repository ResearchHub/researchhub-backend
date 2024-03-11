import decimal
import time

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.models import Balance, RscExchangeRate
from purchase.permissions import CanSendRSC
from purchase.serializers import BalanceSerializer
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from user.models import User
from user.permissions import IsModerator
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

    @action(
        detail=False,
        methods=["GET"],
        permission_classes=[IsAuthenticated],
    )
    def list_csv(self, request):
        queryset = self.get_queryset().values_list("created_date", "amount")
        default_exchange_rate = RscExchangeRate.objects.first()

        data = []
        for obj in queryset.iterator():
            date, rsc = obj
            exchange_rate = RscExchangeRate.objects.filter(
                created_date__lte=date
            ).last()
            if exchange_rate is None:
                rate = default_exchange_rate.real_rate
            else:
                rate = exchange_rate.real_rate
            data.append(
                (
                    date,
                    rsc,
                    rate,
                    f"{(decimal.Decimal(rsc) * decimal.Decimal(rate)):.2f}",
                )
            )
        df = pd.DataFrame(
            data, columns=("date", "rsc_amount", "rsc_to_usd", "usd_value")
        )
        return Response(df.to_csv(index=False), status=200)
