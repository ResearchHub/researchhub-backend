import decimal
import json
import logging
import os
from datetime import datetime, timedelta

import pytz
import requests
import sentry_sdk
from django.contrib.admin.models import LogEntry
from django.contrib.admin.options import get_content_type_for_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from web3 import Web3

from analytics.tasks import track_revenue_event
from notification.models import Notification
from purchase.models import Balance, RscExchangeRate
from reputation.exceptions import WithdrawalError
from reputation.lib import WITHDRAWAL_MINIMUM, PendingWithdrawal, gwei_to_eth
from reputation.models import PaidStatusModelMixin, Webhook, Withdrawal
from reputation.permissions import AllowWithdrawalIfNotSuspecious
from reputation.serializers import WithdrawalSerializer
from researchhub.settings import (
    ETHERSCAN_API_KEY,
    WEB3_KEYSTORE_ADDRESS,
    WEB3_RSC_ADDRESS,
)
from user.models import Action
from user.serializers import UserSerializer
from utils import sentry
from utils.permissions import CreateOrReadOnly, CreateOrUpdateIfAllowed, UserNotSpammer
from utils.throttles import THROTTLE_CLASSES

TRANSACTION_FEE = int(os.environ.get("TRANSACTION_FEE", 100))


class WithdrawalViewSet(viewsets.ModelViewSet):
    queryset = Withdrawal.objects.all()
    serializer_class = WithdrawalSerializer
    permission_classes = [
        IsAuthenticated,
        CreateOrReadOnly,
        CreateOrUpdateIfAllowed,
        UserNotSpammer,
        AllowWithdrawalIfNotSuspecious,
    ]
    throttle_classes = THROTTLE_CLASSES

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Withdrawal.objects.all()
        else:
            return Withdrawal.objects.filter(user=user)

    @action(
        detail=False,
        methods=["POST"],
        permission_classes=[],
    )
    def oz_webhook(self, request):
        body = json.loads(request.body.decode("utf-8"))
        with sentry_sdk.push_scope() as scope:
            scope.set_extra("data", body)
        manual_hook = request.GET.get("manual", False)
        if not manual_hook:
            Webhook.objects.create(body=body, from_host=request.headers["Host"])
        print(body)

        for event in body.get("events", []):
            transaction_hash = event.get("hash")
            from_addr = event.get("transaction", {}).get("from")
            if transaction_hash is None:
                continue

            transfer = False
            for reason in event.get("matchReasons", []):
                if "transfer" in reason.get("signature", "").lower():
                    transfer = True
                    break

            if transfer and Web3.to_checksum_address(
                from_addr
            ) == Web3.to_checksum_address(WEB3_KEYSTORE_ADDRESS):
                withdrawal = Withdrawal.objects.get(transaction_hash=transaction_hash)
                withdrawal.paid_status = PaidStatusModelMixin.PAID
                withdrawal.save()
                withdrawal_content_type = get_content_type_for_model(Withdrawal)
                action, action_created = Action.objects.get_or_create(
                    user=withdrawal.user,
                    content_type=withdrawal_content_type,
                    object_id=withdrawal.id,
                )

                notification, notification_created = Notification.objects.get_or_create(
                    content_type=withdrawal_content_type,
                    object_id=withdrawal.id,
                    action_user=withdrawal.user,
                    recipient=withdrawal.user,
                    notification_type=Notification.RSC_WITHDRAWAL_COMPLETE,
                )

                notification.send_notification()

        return Response(200)

    def create(self, request):
        if LogEntry.objects.filter(
            object_repr="WITHDRAWAL_SWITCH", action_flag=3
        ).exists():
            return Response(
                "Withdrawals are suspended for the time being. Please be patient as we work to turn withdrawals back on",
                status=400,
            )

        user = request.user
        amount = decimal.Decimal(request.data["amount"])
        transaction_fee = self.calculate_transaction_fee()
        to_address = request.data.get("to_address")

        pending_tx = Withdrawal.objects.filter(
            user=user, paid_status="PENDING", transaction_hash__isnull=False
        )

        if pending_tx.exists():
            return Response(
                "Please wait for your previous withdrawal to finish before starting another one.",
                status=400,
            )

        if user.reputation < 120:
            return Response(
                "Your reputation is too low to withdraw. Please contribute to the platform.",
                status=400,
            )

        valid, message = self._check_meets_withdrawal_minimum(amount)
        # if valid:
        #     valid, message = self._check_agreed_to_terms(user, request)
        if valid:
            valid, message = self._check_withdrawal_interval(user, to_address)
        if valid:
            valid, message = self._check_withdrawal_time_limit(to_address, user)

        if valid:
            valid, message, amount = self._check_withdrawal_amount(
                amount, transaction_fee, user
            )
        if valid:
            try:
                withdrawal = Withdrawal.objects.create(
                    user=user,
                    token_address=WEB3_RSC_ADDRESS,
                    to_address=to_address,
                    amount=amount,
                    fee=transaction_fee,
                )

                self._pay_withdrawal(withdrawal, amount, transaction_fee)

                # Track in Amplitude
                track_revenue_event.apply_async(
                    (
                        user.id,
                        "WITHDRAWAL_FEE",
                        str(transaction_fee),
                        None,
                        "ON_CHAIN",
                    ),
                    priority=1,
                )

                serialized = WithdrawalSerializer(withdrawal)
                return Response(serialized.data, status=201)
            except Exception as e:
                sentry.log_error(e)
                return Response(str(e), status=400)
        else:
            sentry.log_info(message)
            return Response(message, status=400)

    def list(self, request):
        # TODO: Do we really need the user on this list? Can we make some
        # changes on the frontend so that we don't need to pass the user here?
        resp = super().list(request)
        resp.data["user"] = UserSerializer(
            request.user, context={"user": request.user}
        ).data
        return resp

    def calculate_transaction_fee(self):
        """
        rsc_to_usd_url = 'https://api.coinbase.com/v2/prices/RSC-USD/spot'
        eth_to_usd_url = 'https://api.coinbase.com/v2/prices/ETH-USD/spot'
        rsc_price = requests.get(rsc_to_usd_url).json()['data']['amount']
        eth_price = requests.get(eth_to_usd_url).json()['data']['amount']
        rsc_to_eth_ratio = rsc_price / eth_price
        return math.ceil(amount * rsc_to_eth_ratio)
        """
        res = requests.get(
            f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={ETHERSCAN_API_KEY}",
            timeout=10,
        )
        json = res.json()
        print(json)
        gas_price = json.get("result", {}).get("SafeGasPrice", 40)
        gas_limit = 120000
        gas_fee_in_eth = gwei_to_eth(int(gas_price) * gas_limit)
        rsc = RscExchangeRate.eth_to_rsc(gas_fee_in_eth)
        return int(rsc)

    # 5 minute cache
    @method_decorator(cache_page(60 * 5))
    @action(detail=False, methods=["get"], permission_classes=[])
    def transaction_fee(self, request):
        fee = self.calculate_transaction_fee()
        return Response(fee, status=200)

    def _create_balance_record(self, withdrawal, amount):
        source_type = ContentType.objects.get_for_model(withdrawal)
        balance_record = Balance.objects.create(
            user=withdrawal.user,
            content_type=source_type,
            object_id=withdrawal.id,
            amount=f"{-amount}",
        )
        return balance_record

    def _pay_withdrawal(self, withdrawal, amount, fee):
        try:
            ending_balance_record = self._create_balance_record(
                withdrawal,
                0,
            )
            pending_withdrawal = PendingWithdrawal(
                withdrawal, ending_balance_record.id, amount
            )
            pending_withdrawal.complete_token_transfer()
            ending_balance_record.amount = f"-{amount + fee}"
            ending_balance_record.save()
        except Exception as e:
            logging.error(e)
            print(e)
            withdrawal.set_paid_failed()
            error = WithdrawalError(e, f"Failed to pay withdrawal {withdrawal.id}")
            logging.error(error)
            sentry.log_error(error, error.message)
            raise e

    def _check_withdrawal_time_limit(self, to_address, user):
        last_withdrawal_address = (
            Withdrawal.objects.filter(
                Q(paid_status="PAID") | Q(paid_status="PENDING"),
                to_address__iexact=to_address,
            )
            .order_by("id")
            .last()
        )
        last_withdrawal_user = (
            Withdrawal.objects.filter(
                Q(paid_status="PAID") | Q(paid_status="PENDING"), user=user
            )
            .order_by("id")
            .last()
        )
        now = datetime.now(pytz.utc)
        if last_withdrawal_address:
            address_timedelta = now - last_withdrawal_address.created_date
        else:
            address_timedelta = now - user.created_date

        if last_withdrawal_user:
            user_timedelta = now - last_withdrawal_user.created_date
        else:
            user_timedelta = now - user.created_date

        user_two_weeks_delta = now - user.created_date

        if user_two_weeks_delta < timedelta(days=14):
            message = "You're account is new, please wait 2 weeks before withdrawing."
            return (False, message)

        if address_timedelta < timedelta(days=14) or user_timedelta < timedelta(
            days=14
        ):
            message = "You're limited to 1 withdrawal every 2 weeks."
            return (False, message)

        return (True, None)

    def _check_meets_withdrawal_minimum(self, balance):
        # Withdrawal amount is full balance for now
        if balance > WITHDRAWAL_MINIMUM:
            return (True, None)

        message = f"Insufficient balance of {balance}"
        if balance > 0:
            message = (
                f"Balance {balance} is below the withdrawal"
                f" minimum of {WITHDRAWAL_MINIMUM}"
            )
        return (False, message)

    def _check_agreed_to_terms(self, user, request):
        agreed = user.agreed_to_terms
        if not agreed:
            agreed = request.data.get("agreed_to_terms", False)
        if agreed == "true" or agreed is True:
            user.agreed_to_terms = True
            user.save()
            return (True, None)
        return (False, "User has not agreed to terms")

    def _check_withdrawal_interval(self, user, to_address):
        """
        Returns True is the user's last withdrawal was more than 2 weeks ago.
        """
        last_withdrawal_tx = (
            Withdrawal.objects.filter(
                Q(paid_status="PAID") | Q(paid_status="PENDING"),
                to_address__iexact=to_address,
            )
            .order_by("id")
            .last()
        )
        if user.withdrawals.count() > 0 or last_withdrawal_tx:
            time_ago = timezone.now() - timedelta(weeks=2)
            minutes_ago = timezone.now() - timedelta(minutes=10)
            last_withdrawal = user.withdrawals.order_by("id").last()
            valid = True
            if last_withdrawal:
                valid = last_withdrawal.created_date < minutes_ago

            if valid:
                last_withdrawal = (
                    user.withdrawals.filter(
                        Q(paid_status="PAID") | Q(paid_status="PENDING")
                    )
                    .order_by("id")
                    .last()
                )
                if not last_withdrawal:
                    return (True, None)
                valid = last_withdrawal.created_date < time_ago
                last_withdrawal_tx_valid = True

                if last_withdrawal_tx:
                    last_withdrawal_tx_valid = (
                        last_withdrawal_tx.created_date < time_ago
                    )

                if valid and last_withdrawal_tx_valid:
                    return (True, None)

                time_since_withdrawal = last_withdrawal.created_date - time_ago
                return (
                    False,
                    "The next time you're able to withdraw is in {} days".format(
                        time_since_withdrawal.days
                    ),
                )
            else:
                time_since_withdrawal = last_withdrawal.created_date - minutes_ago
                minutes = int(round(time_since_withdrawal.seconds / 60, 0))
                return (
                    False,
                    "The next time you're able to withdraw is in {} minutes".format(
                        minutes
                    ),
                )

        return (True, None)

    def _check_withdrawal_amount(self, amount, transaction_fee, user):
        if transaction_fee < 0:
            return (False, "Transaction fee can't be negative", None)

        net_amount = amount - transaction_fee
        if net_amount < 0:
            return (False, "Invalid withdrawal", None)

        if user and user.get_balance() < net_amount:
            return (False, "You do not have enough RSC to make this withdrawal", None)

        return True, None, net_amount
