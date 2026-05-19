from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

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

    @action(
        detail=False,
        methods=["post"],
        permission_classes=[IsAuthenticated],
    )
    def start_deposit_rsc(self, request):
        """
        Create a pending deposit that will be updated by a celery task
        """

        Deposit.objects.create(
            user=request.user,
            amount=request.data.get("amount"),
            from_address=request.data.get("from_address"),
            transaction_hash=request.data.get("transaction_hash"),
            network=request.data.get("network"),
        )

        return Response(200)
