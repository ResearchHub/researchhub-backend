import decimal
import time

import requests
from django.core.cache import cache
from requests.exceptions import HTTPError
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from web3 import Web3

from reputation.distributions import Distribution as Dist
from reputation.distributor import Distributor
from reputation.permissions import DistributionWhitelist

# Do not remove these imports
# Used for urls.py
from reputation.views.bounty_view import BountyViewSet
from reputation.views.deposit_view import DepositViewSet
from reputation.views.withdrawal_view import WithdrawalViewSet
from researchhub.settings import APP_ENV, TRANSPOSE_KEY, WEB3_RSC_ADDRESS
from user.models import User
from utils.http import GET, POST
from utils.sentry import log_error

EXCLUDED_TOKEN_ADDRS = (
    Web3.toChecksumAddress("0xb518536b67720d9d61f5250caf5c0494fc087d3d"),
    Web3.toChecksumAddress("0x4df3043c103a1dc0a80a408f04a2a37f5b0eb662"),
    Web3.toChecksumAddress("0x8b2864a6c0ac9ef7d6c5cc9adbd613407ec671b3"),
    Web3.toChecksumAddress("0x95cccfee95039fb5dfe00839dc6930a07c74877c"),
)


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


@api_view([GET])
@permission_classes([AllowAny])
def get_rsc_circulating_supply(request):
    CACHE_KEY = f"{APP_ENV}_RSC_CIRCULATING_SUPPLY_"

    results = cache.get(CACHE_KEY)
    if results:
        return Response(results, status=200)

    blockchain_supply = get_blockchain_rsc_supply()
    inapp_supply = get_inapp_rsc_supply()
    supply = {
        "RSC Supply": f"{blockchain_supply:,f}",
        "In-App Supply": f"{inapp_supply:,f}",
    }

    cache.set(CACHE_KEY, supply, 60 * 60 * 24)  # Cache expires in a day
    return Response(supply, status=200)


def get_inapp_rsc_supply():
    users = User.objects.filter(balances__isnull=False).order_by("id").distinct()
    return sum([user.get_balance() for user in users.iterator()])


def get_blockchain_rsc_supply():
    BASE_URL = "https://api.transpose.io"
    PAGE_SIZE = 50
    TOKEN_DECIMAL = 18

    headers = {"X-API-KEY": TRANSPOSE_KEY}
    query_params = {"contract_address": WEB3_RSC_ADDRESS, "limit": PAGE_SIZE}
    results = []
    next_link = f"{BASE_URL}/token/owners-by-contract-address"
    while next_link:
        try:
            req = requests.get(next_link, headers=headers, params=query_params)
            req.raise_for_status()
            json_response = req.json()
            results.extend(json_response.get("results", []))
            next_link = json_response.get("next", None)
            time.sleep(0.25)
        except HTTPError as e:
            log_error(e)
            return Response("Error retrieving RSC circulating supply", status=400)

    balances = sum(
        [res["balance"] for res in results if res["owner"] not in EXCLUDED_TOKEN_ADDRS]
    )
    str_balance = str(balances)
    decimal_split = len(str_balance) - TOKEN_DECIMAL
    str_balance = f"{str_balance[:decimal_split]}.{str_balance[decimal_split:]}"
    decimal_balance = decimal.Decimal(str_balance)
    return decimal_balance
