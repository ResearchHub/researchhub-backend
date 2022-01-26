from calendar import monthrange
from django.apps import apps
import datetime
import json
import math
import requests


RSC_TOKEN_ID = "0xd101dcc414f310268c37eeb4cd376ccfa507f571"
UNI_SWAP_BUNDLE_ID = 1
UNI_SWAP_GRAPH_URI = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
USD_PAY_AMOUNT_PER_MONTH = 3000
USD_PER_RSC_PLACEHOLDER = .0001


@apps.task
def editor_daily_payout_task():
    payout_amount = get_daily_rsc_payout_amount()
    # iterate through editors & create distribution


def get_daily_rsc_payout_amount():
    today = datetime.date.today()
    num_days_this_month = monthrange(today.year, today.month)[1]

    uni_swap_query = """{
        rsc: token(id: "%s") {
          derivedETH
        }
        bundle(id: %i) {
          ethPrice
        }
    }""" % (RSC_TOKEN_ID, UNI_SWAP_BUNDLE_ID)
    
    request_result = requests.post(
        UNI_SWAP_GRAPH_URI,
        json={'query': uni_swap_query}
    )
    payload = json.loads(request_result.text).data

    eth_per_rsc = float(payload['rsc']['derivedETH'])
    usd_per_eth = float(payload['bundle']['ethPrice'])
    rsc_per_usd = math.pow(
        (usd_per_eth * eth_per_rsc) or USD_PER_RSC_PLACEHOLDER,
        -1
    )

    return (
      (USD_PAY_AMOUNT_PER_MONTH * rsc_per_usd) / num_days_this_month
    )