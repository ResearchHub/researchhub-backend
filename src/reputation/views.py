from rest_framework import viewsets
from rest_framework.permissions import (
    IsAuthenticated,
    UpdateOrDeleteWithdrawal
)
from rest_framework.response import Response

from reputation.models import Withdrawal
from reputation.serializers import WithdrawalSerializer


class WithdrawalViewset(viewsets.ModelViewSet):
    queryset = Withdrawal.objects.all()
    serializer_class = WithdrawalSerializer
    permission_classes = [IsAuthenticated, UpdateOrDeleteWithdrawal]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Withdrawal.objects.all()
        else:
            return list(user.withdrawals)

    def create(self, request):
        user = request.user
        if user.reputation > 0:
            return super(WithdrawalViewset, self).create(request)
        else:
            return Response('Insufficient reputation', status=400)
