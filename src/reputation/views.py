from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reputation.lib import (
    get_unpaid_distributions,
    get_total_reputation_from_distributions
)
from reputation.models import Withdrawal
from reputation.permissions import UpdateOrDeleteWithdrawal
from reputation.serializers import WithdrawalSerializer


class WithdrawalViewSet(viewsets.ModelViewSet):
    queryset = Withdrawal.objects.all()
    serializer_class = WithdrawalSerializer
    permission_classes = [IsAuthenticated, UpdateOrDeleteWithdrawal]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Withdrawal.objects.all()
        else:
            return list(user.withdrawals.all())

    def create(self, request):
        user = request.user
        unpaid_distributions = get_unpaid_distributions(user)
        total_payout = get_total_reputation_from_distributions(
            unpaid_distributions
        )
        if total_payout > 0:
            return super().create(request)
        else:
            return Response(
                f'Insufficient balance of {total_payout}',
                status=400
            )
