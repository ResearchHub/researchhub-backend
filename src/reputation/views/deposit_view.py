from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from reputation.models import Deposit
from reputation.serializers import DepositSerializer


class DepositViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Deposit.objects.all()
    serializer_class = DepositSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            qs = Deposit.objects.all()
        else:
            qs = Deposit.objects.filter(user=user)

        paid_status = self.request.query_params.get("paid_status")
        if paid_status:
            qs = qs.filter(paid_status=paid_status)

        return qs
