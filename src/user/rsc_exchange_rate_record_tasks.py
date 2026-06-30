import logging

import requests

from purchase.related_models.constants.currency import USD
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate

COIN_GECKO_API_KEY = ""  # currently using free version
RSC_COIN_GECKO_ID = "researchcoin"

logger = logging.getLogger(__name__)


def _coin_gecko_lookup_uri(currency=USD):
    return "https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies={currency}&precision={precision}&x_cg_demo_api_key={coin_gecko_api_key}".format(
        coin_ids=RSC_COIN_GECKO_ID,
        currency=currency,
        precision="10",
        coin_gecko_api_key=COIN_GECKO_API_KEY,
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
    except Exception:
        logger.exception("Failed to record RSC exchange rate")


def get_rsc_price_from_coin_gecko():
    headers = requests.utils.default_headers()
    headers["x-api-key"] = COIN_GECKO_API_KEY
    request_result = requests.get(
        _coin_gecko_lookup_uri(USD), headers=headers, timeout=10
    )
    rate = request_result.json()[RSC_COIN_GECKO_ID]["usd"]
    return {"rate": rate, "real_rate": rate, "target_currency": USD}


def get_rsc_eth_conversion():
    headers = requests.utils.default_headers()
    headers["x-api-key"] = COIN_GECKO_API_KEY
    request_result = requests.get(
        _coin_gecko_lookup_uri("ETH"), headers=headers, timeout=10
    )
    rate = request_result.json()[RSC_COIN_GECKO_ID]["eth"]
    return {"rate": rate, "real_rate": rate, "target_currency": USD}
