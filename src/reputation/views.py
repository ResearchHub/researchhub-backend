from datetime import timedelta, datetime
import pytz
import logging
import decimal

from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action

from purchase.models import Balance
from reputation.exceptions import WithdrawalError
from reputation.lib import (
    WITHDRAWAL_MINIMUM,
    WITHDRAWAL_PER_TWO_WEEKS,
    PendingWithdrawal
)
from reputation.models import Withdrawal
from reputation.serializers import WithdrawalSerializer
from user.serializers import UserSerializer
from utils import sentry
from utils.permissions import CreateOrReadOnly, CreateOrUpdateIfAllowed, UserNotSpammer
from utils.throttles import THROTTLE_CLASSES
from researchhub.settings import WEB3_RSC_ADDRESS


class WithdrawalViewSet(viewsets.ModelViewSet):
    queryset = Withdrawal.objects.all()
    serializer_class = WithdrawalSerializer
    permission_classes = [
        IsAuthenticated,
        CreateOrReadOnly,
        CreateOrUpdateIfAllowed,
        UserNotSpammer
    ]
    throttle_classes = THROTTLE_CLASSES

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Withdrawal.objects.all()
        else:
            return Withdrawal.objects.filter(user=user)

    def create(self, request):
        if timezone.now() < timezone.make_aware(timezone.datetime(2020, 9, 1)):
            return Response(
                'Withdrawals are disabled until September 1, 2020',
                status=400
            )

        user = request.user
        amount = decimal.Decimal(request.data['amount'])
        transaction_fee = request.data.get('transaction_fee', 100)
        to_address = request.data.get('to_address')

        valid, message = self._check_meets_withdrawal_minimum(amount)
        if valid:
            valid, message = self._check_agreed_to_terms(user, request)
        if valid:
            valid, message = self._check_withdrawal_interval(user, to_address)
        if valid:
            valid, message = self._check_withdrawal_time_limit(to_address, user)

        if valid:
            valid, message, amount = self._check_withdrawal_amount(
                amount,
                transaction_fee
            )
        if valid:
            try:

                withdrawal = Withdrawal.objects.create(
                    user=user,
                    token_address=WEB3_RSC_ADDRESS,
                    to_address=to_address,
                    amount=amount
                )
                self._pay_withdrawal(
                    withdrawal,
                    amount
                )

                serialized = WithdrawalSerializer(withdrawal)
                return Response(serialized.data, status=201)
            except Exception as e:
                return Response(str(e), status=400)
        else:
            return Response(message, status=400)

    def list(self, request):
        # TODO: Do we really need the user on this list? Can we make some
        # changes on the frontend so that we don't need to pass the user here?
        resp = super().list(request)
        resp.data['user'] = UserSerializer(request.user, context={'user': request.user}).data
        return resp

    @action(
        detail=False,
        methods=['get'],
        permission_classes=[]
    )
    def transaction_fee(self, request):
        amount = request.query_params.get('amount', 1)
        """
        rsc_to_usd_url = 'https://api.coinbase.com/v2/prices/RSC-USD/spot'
        eth_to_usd_url = 'https://api.coinbase.com/v2/prices/ETH-USD/spot'
        rsc_price = requests.get(rsc_to_usd_url).json()['data']['amount']
        eth_price = requests.get(eth_to_usd_url).json()['data']['amount']
        rsc_to_eth_ratio = rsc_price / eth_price
        return math.ceil(amount * rsc_to_eth_ratio)
        """

        return Response(100, status=200)

    def _create_balance_record(self, withdrawal, amount):
        source_type = ContentType.objects.get_for_model(withdrawal)
        balance_record = Balance.objects.create(
            user=withdrawal.user,
            content_type=source_type,
            object_id=withdrawal.id,
            amount=f'{amount}',
        )
        return balance_record

    def _pay_withdrawal(self, withdrawal, amount):
        try:
            ending_balance_record = self._create_balance_record(
                withdrawal,
                0,
            )
            pending_withdrawal = PendingWithdrawal(
                withdrawal,
                ending_balance_record.id,
                amount
            )
            pending_withdrawal.complete_token_transfer()
            ending_balance_record.amount = f'-{amount}'
            ending_balance_record.save()
        except Exception as e:
            logging.error(e)
            withdrawal.set_paid_failed()
            error = WithdrawalError(
                e,
                f'Failed to pay withdrawal {withdrawal.id}'
            )
            logging.error(error)
            sentry.log_error(error, error.message)
            raise e

    def _check_withdrawal_time_limit(self, to_address, user):
        last_withdrawal_address = Withdrawal.objects.filter(Q(paid_status='PAID') | Q(paid_status='PENDING'), to_address__iexact=to_address).order_by('id').last()
        last_withdrawal_user = Withdrawal.objects.filter(Q(paid_status='PAID') | Q(paid_status='PENDING'), user=user).order_by('id').last()
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
            message = (
                "You're account is new, please wait 2 weeks before withdrawing."
            )
            return (False, message)

        if address_timedelta < timedelta(days=14) or user_timedelta < timedelta(days=14):
            message = (
                "You're limited to 1 withdrawal every 2 weeks."
            )
            return (False, message)

        return (True, None)

    def _check_meets_withdrawal_minimum(self, balance):
        # Withdrawal amount is full balance for now
        if balance > WITHDRAWAL_MINIMUM:
            return (True, None)

        message = f'Insufficient balance of {balance}'
        if balance > 0:
            message = (
                f'Balance {balance} is below the withdrawal'
                f' minimum of {WITHDRAWAL_MINIMUM}'
            )
        return (False, message)

    def _check_agreed_to_terms(self, user, request):
        agreed = user.agreed_to_terms
        if not agreed:
            agreed = request.data.get('agreed_to_terms', False)
        if agreed == 'true' or agreed is True:
            user.agreed_to_terms = True
            user.save()
            return (True, None)
        return (False, 'User has not agreed to terms')

    def _check_withdrawal_interval(self, user, to_address):
        """
        Returns True is the user's last withdrawal was more than 2 weeks ago.
        """
        last_withdrawal_tx = Withdrawal.objects.filter(Q(paid_status='PAID') | Q(paid_status='PENDING'), to_address__iexact=to_address).order_by('id').last()
        if user.withdrawals.count() > 0 or last_withdrawal_tx:
            time_ago = timezone.now() - timedelta(weeks=2)
            minutes_ago = timezone.now() - timedelta(minutes=10)
            last_withdrawal = user.withdrawals.order_by('id').last()
            valid = True
            if last_withdrawal:
                valid = last_withdrawal.created_date < minutes_ago

            if valid:
                last_withdrawal = user.withdrawals.filter(Q(paid_status='PAID') | Q(paid_status='PENDING')).order_by('id').last()
                if not last_withdrawal:
                    return (True, None)
                valid = last_withdrawal.created_date < time_ago
                last_withdrawal_tx_valid = True

                if last_withdrawal_tx:
                    last_withdrawal_tx_valid = last_withdrawal_tx.created_date < time_ago

                if valid and last_withdrawal_tx:
                    return (True, None)

                time_since_withdrawal = last_withdrawal.created_date - time_ago
                return (False, "The next time you're able to withdraw is in {} days".format(time_since_withdrawal.days))
            else:
                time_since_withdrawal = last_withdrawal.created_date - minutes_ago
                minutes = int(round(time_since_withdrawal.seconds / 60, 0))
                return (False, "The next time you're able to withdraw is in {} minutes".format(minutes))

        return (True, None)

    def _check_withdrawal_amount(self, amount, transaction_fee):
        if transaction_fee <= 0:
            return (False, "Transaction fee can't be zero", None)

        net_amount = amount - transaction_fee
        if amount - transaction_fee < 0:
            return (False, "Invalid withdrawal", None)

        return True, None, net_amount
