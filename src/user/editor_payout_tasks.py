from calendar import monthrange
from django.apps import apps
from django.contrib.contenttypes.models import ContentType
import datetime
import json
import math
import requests

from hub.models import Hub
from purchase.models import Balance
from reputation.models import Distribution
from researchhub_access_group.constants import EDITOR
from researchhub_document.related_models.constants.rsc_exchange_currency import USD
from researchhub_document.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub.settings import WEB3_RSC_ADDRESS
from user.related_models.user_model import User

UNI_SWAP_BUNDLE_ID = 1  # their own hard-coded eth-bundle id
UNI_SWAP_GRAPH_URI = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
USD_PAY_AMOUNT_PER_MONTH = 3000
USD_PER_RSC_DEFAULT = .01

# TODO: (kobe) - API is under Calvin. Need to move to RH's account
MORALIS_API_KEY = 'vlHzigIN9AYgxwTV2y55ruHrUYc08WsMFCTZNn4mUSLzJAdWMW5pCnUtrL0yqlwE'
MORALIS_LOOKUP_URI = "https://deep-index.moralis.io/api/v2/erc20/{address}/price".format(address=WEB3_RSC_ADDRESS)


@apps.task
def editor_daily_payout_task():
    today = datetime.date.today()
    num_days_this_month = monthrange(today.year, today.month)[1]
    result = get_daily_rsc_payout_amount_from_deep_index(num_days_this_month)
    RscExchangeRate.objects.create(
      rate=result['rate'],
      target_currency=USD,
    )
    editors = User.objects.filter(
        permissions__isnull=False,
        permissions__access_type=EDITOR,
        permissions__content_type=ContentType.objects.get_for_model(Hub)
    ).distinct()
    for editor in editors.iterator():
        pay_amount = result['pay_amount']
        rsc_distribution = Distribution.objects.create(
            amount=pay_amount,
            distributed_date=today,
            distributed_status='DISTRIBUTED',
            distribution_type='EDITOR_COMPENSATION',
            proof={
                'record': {'user_id': editor.id},
                'table': 'user_user',
            },
            proof_item_content_type=ContentType.objects.get_for_model(User),
            proof_item_object_id=editor.id,
            recipient=editor,
        )
        Balance.objects.create(
            user=editor,
            amount=str(pay_amount),
            content_type=ContentType.objects.get_for_model(Distribution),
            object_id=rsc_distribution.id
        )


def get_daily_rsc_payout_amount_from_deep_index(num_days_this_month):
    headers = requests.utils.default_headers()
    headers['x-api-key'] = MORALIS_API_KEY
    request_result = requests.get(
        MORALIS_LOOKUP_URI,
        headers=headers
    )
    real_usd_per_rsc = json.loads(request_result.text)['usdPrice']
    payout_usd_per_rsc = real_usd_per_rsc if \
        real_usd_per_rsc > USD_PER_RSC_DEFAULT \
        else USD_PER_RSC_DEFAULT
    return (
      {
          'rate': payout_usd_per_rsc,
          'pay_amount': (
              USD_PAY_AMOUNT_PER_MONTH * math.pow(payout_usd_per_rsc, -1) / num_days_this_month
          )
      }
    )


def get_daily_rsc_payout_amount_from_uniswap(num_days_this_month):
    today = datetime.date.today()
    num_days_this_month = monthrange(today.year, today.month)[1]

    uni_swap_query = """{
        rsc: token(id: "%s") {
          derivedETH
        }
        bundle(id: %i) {
          ethPrice
        }
    }""" % (WEB3_RSC_ADDRESS, UNI_SWAP_BUNDLE_ID)
    
    request_result = requests.post(
        UNI_SWAP_GRAPH_URI,
        json={'query': uni_swap_query}
    )
    payload = json.loads(request_result.text).data

    eth_per_rsc = float(payload['rsc']['derivedETH'])
    usd_per_eth = float(payload['bundle']['ethPrice'])
    rsc_per_usd = math.pow(
        (usd_per_eth * eth_per_rsc) or USD_PER_RSC_DEFAULT,
        -1
    )

    return (
      USD_PAY_AMOUNT_PER_MONTH * rsc_per_usd / num_days_this_month
    )
