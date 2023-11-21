import json

import requests

from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from utils.sentry import log_error

COIN_GECKO_API_KEY = ""  # currently using free version
RSC_COIN_GECKO_ID = "researchcoin"
RECORDED_CURRENCY = USD


def COIN_GECKO_LOOKUP_URI(currency=USD):
    return "https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies={currency}&precision={precision}".format(
        coin_ids=RSC_COIN_GECKO_ID, currency=currency, precision="10"
    )


def rsc_exchange_rate_record_tasks():
    try:
        gecko_result = get_rsc_price_from_coin_gecko()
        RscExchangeRate.objects.create(
            price_source=COIN_GECKO,
            rate=gecko_result["rate"],
            real_rate=gecko_result["real_rate"],
            target_currency=USD,
        )
        return gecko_result
    except Exception as error:
        log_error(error)


def get_rsc_price_from_coin_gecko():
    headers = requests.utils.default_headers()
    headers["x-api-key"] = COIN_GECKO_API_KEY
    request_result = requests.get(COIN_GECKO_LOOKUP_URI(USD), headers=headers)
    rate = request_result.json()[RSC_COIN_GECKO_ID]["usd"]
    return {"rate": rate, "real_rate": rate, "target_currency": USD}


def get_rsc_eth_conversion():
    headers = requests.utils.default_headers()
    headers["x-api-key"] = COIN_GECKO_API_KEY
    request_result = requests.get(COIN_GECKO_LOOKUP_URI("ETH"), headers=headers)
    rate = request_result.json()[RSC_COIN_GECKO_ID]["eth"]
    return {"rate": rate, "real_rate": rate, "target_currency": USD}
