from datetime import timedelta, datetime
import pytz
import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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
        starting_balance = user.get_balance()

        valid, message = self._check_meets_withdrawal_minimum(starting_balance)
        if valid:
            valid, message = self._check_agreed_to_terms(user, request)
        if valid:
            valid, message = self._check_withdrawal_interval(user)
        if valid:
            valid, message = self._check_withdrawal_time_limit(request.data.get('to_address'), user)
        if valid:
            try:
                to_address = request.data['to_address']
                amount = request.data['amount']
                withdrawal = Withdrawal.objects.create(
                    user=user,
                    token_address=WEB3_RSC_ADDRESS,
                    to_address=to_address,
                    amount=amount
                )
                ending_balance_record = self._create_balance_record(
                    withdrawal,
                    starting_balance
                )
                self._pay_withdrawal(
                    withdrawal,
                    starting_balance,
                    ending_balance_record.id
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

    def _create_balance_record(self, withdrawal, amount):
        source_type = ContentType.objects.get_for_model(withdrawal)
        balance_record = Balance.objects.create(
            user=withdrawal.user,
            content_type=source_type,
            object_id=withdrawal.id,
            amount=f'-{amount}',
        )
        return balance_record

    def _pay_withdrawal(self, withdrawal, starting_balance, balance_record_id):
        try:
            pending_withdrawal = PendingWithdrawal(
                withdrawal,
                starting_balance,
                balance_record_id
            )
            pending_withdrawal.complete_token_transfer()
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
        last_withdrawal_address = Withdrawal.objects.filter(to_address=to_address).last()
        last_withdrawal_user = Withdrawal.objects.filter(user=user).last()
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

    def _check_withdrawal_interval(self, user):
        """
        Returns True is the user's last withdrawal was more than 72 hours ago.
        """
        if user.withdrawals.count() > 0:
            time_ago = timezone.now() - timedelta(hours=72)
            valid = user.withdrawals.last().created_date < time_ago
            if valid:
                return (True, None)
            return (False, 'Too soon to withdraw again')
        return (True, None)
