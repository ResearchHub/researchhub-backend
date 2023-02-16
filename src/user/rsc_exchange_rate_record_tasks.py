import json
import requests

from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate

COIN_GECKO_API_KEY = "" # currently using free version
RSC_COIN_GECKO_ID = "researchcoin"
RECORDED_CURRENCY = USD
COIN_GECKO_LOOKUP_URI = "https://api.coingecko.com/api/v3/simple/price?ids={coin_ids}&vs_currencies={currency}&precision=${precision}".format(
    coin_ids=RSC_COIN_GECKO_ID, currency=USD, precision="10"
)


def rsc_exchange_rate_record_tasks():
    gecko_result = get_rsc_price_from_coin_gecko()
    RscExchangeRate.objects.create(
        price_source=COIN_GECKO,
        rate=gecko_result["rate"],
        real_rate=gecko_result["real_rate"],
        target_currency=USD,
    )


def get_rsc_price_from_coin_gecko():
    headers = requests.utils.default_headers()
    headers["x-api-key"] = COIN_GECKO_API_KEY
    request_result = requests.get(COIN_GECKO_LOOKUP_URI, headers=headers)
    rate = json.loads(request_result.text)[RSC_COIN_GECKO_ID]["usd"]
    return {"rate": rate, "real_rate": rate, "target_currency": USD}
