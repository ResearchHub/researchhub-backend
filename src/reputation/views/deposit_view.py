from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from reputation.models import Deposit
from reputation.serializers import DepositSerializer
from reputation.tasks import check_deposits


class DepositViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Deposit.objects.all()
    serializer_class = DepositSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            return Deposit.objects.all()
        else:
            return Deposit.objects.filter(user=user)

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

        check_deposits.delay()

        return Response(200)
