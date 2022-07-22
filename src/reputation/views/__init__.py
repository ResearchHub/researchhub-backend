import time

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.permissions import DistributionWhitelist
from reputation.views.bounty_view import BountyViewSet
from reputation.views.deposit_view import DepositViewSet
from reputation.views.withdrawal_view import WithdrawalViewSet
from user.models import User
from utils.http import POST


@api_view(http_method_names=[POST])
@permission_classes([DistributionWhitelist])
def distribute_rsc(request):
    data = request.data
    recipient_id = data.get("recipient_id")
    amount = data.get("amount")

    user = User.objects.get(id=recipient_id)
    distribution = Dist("REWARD", amount, give_rep=False)
    distributor = Distributor(distribution, user, user, time.time(), user)
    distributor.distribute()

    response = Response({"data": f"Gave {amount} RSC to {user.email}"}, status=200)
    return response
