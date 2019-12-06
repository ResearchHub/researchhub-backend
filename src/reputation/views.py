from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reputation.lib import get_user_balance
from reputation.models import Withdrawal
from reputation.serializers import WithdrawalSerializer
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
        user_balance = get_user_balance(user)
        if user_balance > 0:
            response = super().create(request)
            withdrawal_id = response.data['id']
            withdrawal = Withdrawal.objects.get(pk=withdrawal_id)
            serialized = WithdrawalSerializer(withdrawal)
            return Response(serialized.data, status=201)
        else:
            return Response(
                f'Insufficient balance of {user_balance}',
                status=400
            )
