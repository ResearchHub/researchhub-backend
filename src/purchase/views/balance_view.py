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

    @staticmethod
    def get_transaction_type(balance) -> str:
        """
        Map balance content type to TurboTax transaction type.
        
        Rules:
        - withdrawal -> Withdrawal
        - deposit -> Deposit
        - *fee* in type -> Expense
        - negative RSC amount -> Buy
        - positive RSC amount -> Income
        """
        model_name = balance.content_type.model.lower()
        
        # First check for specific model names
        if model_name == "withdrawal":
            return "Withdrawal"
        if model_name == "deposit":
            return "Deposit"
        
        # Check for fee in the model name or description
        if "fee" in model_name:
            return "Expense"
            
        # For all other transactions, base it on amount
        return "Buy" if Decimal(balance.amount) < 0 else "Income"

    @staticmethod
    def format_decimal(value: Optional[Decimal]) -> str:
        """Format decimal to 8 decimal places."""
        if value is None:
            return "0.00"
        # Convert to string with proper decimal formatting
        return "{:.8f}".format(float(value)) 
    
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
    def list_csv_turbotax(self, request):
        default_exchange_rate = RscExchangeRate.objects.first()
        
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="transactions_turbotax.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            "Date",
            "Type",
            "Sent Asset",
            "Sent Amount",
            "Received Asset",
            "Received Amount",
            "Fee Asset",
            "Fee Amount",
            "Market Value Currency",
            "Market Value",
            "Description",
            "Transaction Hash",
            "Transaction ID"
        ])

        for balance in self.get_queryset().iterator():
            exchange_rate = RscExchangeRate.objects.filter(
                created_date__lte=balance.created_date
            ).last()
            
            if exchange_rate is None:
                rate = default_exchange_rate.real_rate or Decimal('0.00')
            else:
                rate = exchange_rate.real_rate or exchange_rate.rate or Decimal('0.00')

            transaction_type = self.get_transaction_type(balance)
            amount = abs(Decimal(balance.amount))  # Use absolute value for amounts
            usd_value = amount * Decimal(rate)
            
            # Determine if this is a send or receive based on amount sign
            is_negative = Decimal(balance.amount) < 0
            
            # Format the row based on transaction type and amount sign
            if is_negative or transaction_type in ["Withdrawal", "Expense"]:
                row = [
                    balance.created_date.strftime("%Y-%m-%d %H:%M:%S"),
                    transaction_type,
                    "RSC",  # Sent Asset
                    self.format_decimal(amount),  # Sent Amount (positive)
                    "",  # Received Asset
                    "",  # Received Amount
                    "",  # Fee Asset
                    "",  # Fee Amount
                    "USD",  # Market Value Currency
                    self.format_decimal(usd_value),  # Market Value
                    balance.content_type.name,  # Description
                    "",  # Transaction Hash
                    str(balance.id)  # Transaction ID
                ]
            else:  # Positive amounts and other transaction types
                row = [
                    balance.created_date.strftime("%Y-%m-%d %H:%M:%S"),
                    transaction_type,
                    "",  # Sent Asset
                    "",  # Sent Amount
                    "RSC",  # Received Asset
                    self.format_decimal(amount),  # Received Amount (positive)
                    "",  # Fee Asset
                    "",  # Fee Amount
                    "USD",  # Market Value Currency
                    self.format_decimal(usd_value),  # Market Value
                    balance.content_type.name,  # Description
                    "",  # Transaction Hash
                    str(balance.id)  # Transaction ID
                ]

            writer.writerow(row)

        return response
