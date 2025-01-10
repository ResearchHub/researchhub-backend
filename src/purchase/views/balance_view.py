import csv
import decimal
import time
from datetime import datetime
from typing import Optional
from decimal import Decimal

import pytz
from django.contrib.contenttypes.models import ContentType
from django.http import HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django_filters import rest_framework as filters

from purchase.models import Balance, RscExchangeRate
from purchase.permissions import CanSendRSC
from purchase.serializers import BalanceSerializer
from reputation.distributions import Distribution
from reputation.distributor import Distributor
from user.models import User
from user.permissions import IsModerator
from utils.throttles import THROTTLE_CLASSES


class BalanceFilter(filters.FilterSet):
    created_date = filters.DateTimeFromToRangeFilter()

    class Meta:
        model = Balance
        fields = ['created_date']


class BalanceViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Balance.objects.all()
    serializer_class = BalanceSerializer
    filterset_class = BalanceFilter
    filter_backends = [filters.DjangoFilterBackend]
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
        default_exchange_rate = RscExchangeRate.objects.first()

        before_exchange_rate_date = "11-10-2022"
        before_exchange_datetime = datetime.strptime(
            before_exchange_rate_date, "%m-%d-%Y"
        )
        specific_date_aware = pytz.utc.localize(before_exchange_datetime)

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="transactions.csv"'

        writer = csv.writer(response)
        writer.writerow(
            ["date", "rsc_amount", "rsc_to_usd", "usd_value", "description"]
        )

        for balance in self.get_queryset().iterator():
            exchange_rate = RscExchangeRate.objects.filter(
                created_date__lte=balance.created_date
            ).last()
            if exchange_rate is None:
                rate = default_exchange_rate.real_rate
            else:
                # Uses rate if real_rate is null
                rate = exchange_rate.real_rate or exchange_rate.rate

            if (
                balance.created_date <= specific_date_aware
                and exchange_rate is None
                or not exchange_rate.real_rate
            ):
                rate = 0

            writer.writerow(
                [
                    balance.created_date,
                    balance.amount,
                    rate,
                    f"{(decimal.Decimal(balance.amount) * decimal.Decimal(rate)):.2f}",
                    balance.content_type.name,
                ]
            )

        return response

    @action(
        detail=False,
        methods=["GET"],
        permission_classes=[IsAuthenticated],
    )
    def turbotax_csv_export(self, request):
        """Export transactions in TurboTax-compatible CSV format."""
        
        def format_decimal(value: Optional[Decimal]) -> str:
            """Format decimal to 8 decimal places."""
            if value is None:
                return "0.00"
            return "{:.8f}".format(float(value))
        
        def get_transaction_type_for_turbotax(balance) -> str:
            """
            Map balance content type to TurboTax transaction type.
            
            Rules:
            - withdrawal -> Withdrawal
            - deposit -> Deposit
            - *fee* in type -> Expense
            - negative RSC amount -> Buy
            - positive RSC amount -> Income
            
            Turbotax CSV format:
            https://ttlc.intuit.com/turbotax-support/en-us/help-article/
            cryptocurrency/create-csv-file-unsupported-source/L1yhp71Nt_US_en_US?
            """
            model_name = balance.content_type.model.lower()
            
            if model_name == "withdrawal":
                return "Withdrawal"
            if model_name == "deposit":
                return "Deposit"
            if "fee" in model_name:
                return "Expense"
            return "Buy" if Decimal(balance.amount) < 0 else "Income"

        def format_transaction_row(balance, rate: Decimal) -> list:
            """Format a single transaction row for TurboTax CSV."""
            amount = abs(Decimal(balance.amount))
            usd_value = amount * Decimal(rate)
            transaction_type = get_transaction_type_for_turbotax(balance)
            is_outgoing = (
                Decimal(balance.amount) < 0 or transaction_type == "Withdrawal"
            )

            base_row = [
                balance.created_date.strftime("%Y-%m-%d %H:%M:%S"),
                transaction_type,
                "",  # Sent Asset
                "",  # Sent Amount
                "",  # Received Asset
                "",  # Received Amount
                "",  # Fee Asset
                "",  # Fee Amount
                "USD",  # Market Value Currency
                format_decimal(usd_value),  # Market Value
                balance.content_type.name,  # Description
                "",  # Transaction Hash
                str(balance.id)  # Transaction ID
            ]

            if is_outgoing:
                base_row[2] = "RSC"  # Sent Asset
                base_row[3] = format_decimal(amount)  # Sent Amount
            else:
                base_row[4] = "RSC"  # Received Asset
                base_row[5] = format_decimal(amount)  # Received Amount

            return base_row

        default_exchange_rate = RscExchangeRate.objects.first()
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="transactions_turbotax.csv"'
        )
        
        writer = csv.writer(response)
        headers = [
            "Date", "Type", "Sent Asset", "Sent Amount", "Received Asset",
            "Received Amount", "Fee Asset", "Fee Amount",
            "Market Value Currency", "Market Value", "Description",
            "Transaction Hash", "Transaction ID"
        ]
        writer.writerow(headers)

        for balance in self.get_queryset().iterator():
            exchange_rate = RscExchangeRate.objects.filter(
                created_date__lte=balance.created_date
            ).last()
            
            rate = (
                exchange_rate.real_rate or exchange_rate.rate
                if exchange_rate
                else default_exchange_rate.real_rate
            ) or Decimal('0.00')

            row = format_transaction_row(balance, rate)
            writer.writerow(row)

        return response
