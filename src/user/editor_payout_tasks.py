from calendar import monthrange
from django.apps import apps
import json
import requests
import datetime


RSC_TOKEN_ID = "0xd101dcc414f310268c37eeb4cd376ccfa507f571"
UNI_SWAP_BUNDLE_ID = 1
UNI_SWAP_GRAPH_URI = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
USD_PAY_AMOUNT_PER_MONTH = 3000


@apps.task
def editor_daily_payout_task():
    today = datetime.date.today()
    num_days_this_month = monthrange(today.year, today.month)[1]

    query = """{
        rsc: token(id: "%s") {
          derivedETH
        }
        bundle(id: %i) {
          ethPrice
        }
    }""" % (RSC_TOKEN_ID, UNI_SWAP_BUNDLE_ID)
    request_result = requests.post(
        UNI_SWAP_GRAPH_URI,
        json={'query': query}
    )
    payload = json.loads(request_result.text)
    eth_per_rsc = payload['rsc']['derivedETH']
    usd_per_eth = payload['bundle']['ethPrice']
    rsc_per_usd = (usd_per_eth * eth_per_rsc) ** -1

    rsc_pay_amount = (
      (USD_PAY_AMOUNT_PER_MONTH * rsc_per_usd) / num_days_this_month
    )
