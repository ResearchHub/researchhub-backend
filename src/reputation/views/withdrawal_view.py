import decimal
import logging
import math
import os
from datetime import datetime, timedelta

import pytz
import requests
from django.conf import settings
from django.contrib.admin.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from analytics.tasks import track_revenue_event
from purchase.models import Balance, RscExchangeRate
from reputation.exceptions import WithdrawalError
from reputation.lib import (
    WITHDRAWAL_MINIMUM,
    PendingWithdrawal,
    get_hotwallet_rsc_balance,
    gwei_to_eth,
)
from reputation.models import Withdrawal
from reputation.permissions import AllowWithdrawalIfNotSuspecious
from reputation.serializers import WithdrawalSerializer
from user.related_models.user_model import User
from user.related_models.user_verification_model import UserVerification
from user.serializers import UserSerializer
from utils import sentry
from utils.permissions import CreateOrReadOnly, CreateOrUpdateIfAllowed, UserNotSpammer
from utils.throttles import THROTTLE_CLASSES

NETWORKS = {
    "ETHEREUM": {
        "provider_url": settings.WEB3_PROVIDER_URL,
        "token_address": settings.WEB3_RSC_ADDRESS,
    },
    "BASE": {
        "provider_url": os.environ.get(
            "WEB3_BASE_PROVIDER_URL", "https://sepolia.base.org"
        ),
        "token_address": os.environ.get(
            "WEB3_BASE_RSC_ADDRESS", settings.WEB3_RSC_ADDRESS
        ),
    },
}

logger = logging.getLogger(__name__)


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

    def create(self, request):
        amount = decimal.Decimal(request.data["amount"])
        to_address = request.data.get("to_address")
        user = request.user

        if LogEntry.objects.filter(
            object_repr="WITHDRAWAL_SWITCH", action_flag=3
        ).exists():
            logger.info(
                f"Withdrawals suspended; request blocked for user {user.id} "
                f"(amount: {amount}, to_address: {to_address})"
            )
            return Response(
                "Withdrawals are suspended for the time being. "
                "Please be patient as we work to turn withdrawals back on",
                status=400,
            )

        network = request.data.get("network", "ETHEREUM").upper()
        if network not in NETWORKS:
            return Response(
                "Invalid network. Please choose either 'BASE' or 'ETHEREUM'", status=400
            )

        transaction_fee = self.calculate_transaction_fee(network)

        pending_tx = Withdrawal.objects.filter(
            user=user, paid_status="PENDING", transaction_hash__isnull=False
        )

        if pending_tx.exists():
            return Response(
                "Please wait for your previous withdrawal to finish "
                "before starting another one.",
                status=400,
            )

        if not self._can_withdraw(user):
            return Response(
                "Your reputation is too low to withdraw. "
                "Please claim papers you have authored and contribute to the "
                "community to increase your reputation. "
                "Alternatively, verify your identity to withdraw.",
                status=400,
            )

        valid, message = self._check_meets_withdrawal_minimum(amount)
        if valid:
            valid, message = self._check_withdrawal_interval(user, to_address)
        if valid:
            valid, message = self._check_withdrawal_time_limit(to_address, user)

        if valid:
            valid, message = self._check_hotwallet_balance(amount, network)

        if valid:
            try:
                with transaction.atomic():
                    # Lock the user record to prevent race conditions during withdrawal
                    user = User.objects.select_for_update().get(id=user.id)

                    valid, message, amount = self._check_withdrawal_amount(
                        amount, transaction_fee, user
                    )

                    if not valid:
                        return Response(message, status=400)

                    withdrawal = Withdrawal.objects.create(
                        user=user,
                        token_address=NETWORKS[network]["token_address"],
                        to_address=to_address,
                        amount=amount,
                        fee=transaction_fee,
                        network=network,
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
            logger.error(f"Invalid withdrawal: {message}")
            return Response(message, status=400)

    def _can_withdraw(self, user: User) -> bool:
        # User can withdraw if rep score is 10 or more
        if user.author_profile.get_rep_score() >= 10:
            return True

        # ...or if the user's identity has been verified
        user_verification = UserVerification.objects.filter(user=user).first()
        if not user_verification:
            return False

        return user_verification.is_verified

    def _min_time_between_withdrawals(self, user: User) -> timedelta:
        user_verification = UserVerification.objects.filter(user=user).first()
        if user_verification and user_verification.is_verified:
            # Verified users can withdraw every 24 hours
            return timedelta(days=1)

        return timedelta(weeks=2)

    def _min_time_between_withdrawals_message(self, user: User) -> str:
        user_verification = UserVerification.objects.filter(user=user).first()
        if user_verification and user_verification.is_verified:
            # Verified users can withdraw every 24 hours
            return "You're limited to 1 withdrawal a day."

        return "You're limited to 1 withdrawal every 2 weeks."

    def list(self, request):
        # TODO: Do we really need the user on this list? Can we make some
        # changes on the frontend so that we don't need to pass the user here?
        resp = super().list(request)
        resp.data["user"] = UserSerializer(
            request.user, context={"user": request.user}
        ).data
        return resp

    def calculate_transaction_fee(self, network="ETHEREUM"):
        """
        Calculate the transaction fee based on the network.
        Base network typically has lower fees than Ethereum.
        """

        if network == "BASE":
            # Get gas price from Basescan API
            res = requests.get(
                f"https://api.basescan.org/api"
                f"?module=proxy"
                f"&action=eth_gasPrice"
                f"&apikey={settings.BASESCAN_API_KEY}",
                timeout=10,
            )
            json = res.json()
            gas_price_wei = int(json.get("result", "0x0"), 16)  # Convert hex to int
            gas_price = gas_price_wei / 10**9  # Convert wei to gwei
        else:
            # For Ethereum network
            res = requests.get(
                f"https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={settings.ETHERSCAN_API_KEY}",
                timeout=10,
            )
            json = res.json()
            gas_price = json.get("result", {}).get("SafeGasPrice", 40)

        gas_limit = (
            120000.0  # Maximum amount of gas we are willing to consume on a transaction
        )

        gas_fee_in_eth = gwei_to_eth(float(gas_price) * gas_limit)
        rsc = RscExchangeRate.eth_to_rsc(gas_fee_in_eth)
        return decimal.Decimal(str(math.ceil(rsc * 100) / 100))

    # 5 minute cache
    @method_decorator(cache_page(60 * 5))
    @action(detail=False, methods=["get"], permission_classes=[])
    def transaction_fee(self, request):
        network = request.GET.get("network", "ETHEREUM").upper()
        fee = self.calculate_transaction_fee(network)

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
                withdrawal, ending_balance_record.id, amount, network=withdrawal.network
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

        user_verification = UserVerification.objects.filter(user=user).first()
        is_user_verified = user_verification and user_verification.is_verified

        if user_two_weeks_delta < timedelta(days=14) and not is_user_verified:
            message = "You're account is new, please wait 2 weeks before withdrawing."
            return (False, message)

        min_time_between_withdrawals = self._min_time_between_withdrawals(user)

        if (
            address_timedelta < min_time_between_withdrawals
            or user_timedelta < min_time_between_withdrawals
        ):
            message = self._min_time_between_withdrawals_message(user)
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
            time_ago = timezone.now() - self._min_time_between_withdrawals(user)
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

    def _check_hotwallet_balance(
        self, amount, network="ETHEREUM"
    ) -> tuple[bool, str | None]:
        if network == "ETHEREUM":
            rsc_balance_eth = get_hotwallet_rsc_balance()
        else:
            rsc_balance_eth = get_hotwallet_rsc_balance(network="BASE")

        if rsc_balance_eth < amount:
            return (False, "Hotwallet balance is lower than the withdrawal amount")
        return (True, None)
