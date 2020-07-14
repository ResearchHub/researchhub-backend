import logging
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from purchase.models import Balance
from reputation.exceptions import WithdrawalError
from reputation.lib import (
    FIRST_WITHDRAWAL_MINIMUM,
    PendingWithdrawal
)
from reputation.models import Withdrawal
from reputation.serializers import WithdrawalSerializer
from user.serializers import UserSerializer
from utils import sentry
from utils.permissions import CreateOrReadOnly


class WithdrawalViewSet(viewsets.ModelViewSet):
    queryset = Withdrawal.objects.all()
    serializer_class = WithdrawalSerializer
    permission_classes = [IsAuthenticated, CreateOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Withdrawal.objects.all()
        else:
            return Withdrawal.objects.filter(user=user)

    def create(self, request):
        user = request.user
        starting_balance = user.get_balance()
        if self._check_meets_withdrawal_minimum(user, starting_balance):
            if not user.agreed_to_terms:
                user.agreed_to_terms = request.data.get(
                    'agreed_to_terms',
                    False
                )
                user.save()
            try:
                with transaction.atomic():
                    response = super().create(request)
                    withdrawal_id = response.data['id']
                    withdrawal = Withdrawal.objects.get(pk=withdrawal_id)
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
            message = f'Insufficient balance of {starting_balance}'
            if starting_balance > 0:
                message = (
                    f'Balance {starting_balance} is below the withdrawal'
                    f' minimum of {FIRST_WITHDRAWAL_MINIMUM}'
                )
            return Response(message, status=400)

    def list(self, request):
        # TODO: Do we really need the user on this list? Can we make some
        # changes on the frontend so that we don't need to pass the user here?
        resp = super().list(request)
        resp.data['user'] = UserSerializer(request.user).data
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

    def _check_meets_withdrawal_minimum(self, user, balance):
        # Withdrawal amount is full balance for now
        if user.withdrawals.count() < 1:
            return balance >= FIRST_WITHDRAWAL_MINIMUM
        return balance > 0
