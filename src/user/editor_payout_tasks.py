import datetime
import json
import math
from calendar import monthrange

import requests
from django.apps import apps
from django.contrib.contenttypes.models import ContentType

from hub.models import Hub
from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO, USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution  # this is NOT the model
from researchhub.settings import MORALIS_API_KEY, WEB3_RSC_ADDRESS
from researchhub_access_group.constants import EDITOR
from user.constants.gatekeeper_constants import (
    EDITOR_PAYOUT_ADMIN,
    PAYOUT_EXCLUSION_LIST,
)
from user.related_models.gatekeeper_model import Gatekeeper
from utils import sentry

UNI_SWAP_BUNDLE_ID = 1  # their own hard-coded eth-bundle id
UNI_SWAP_GRAPH_URI = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
# TODO: calvinhlee consider moving these to ENV variable
USD_PAY_AMOUNT_PER_MONTH = 1000
USD_PER_RSC_PRICE_FLOOR = 0.01

MORALIS_LOOKUP_URI = (
    "https://deep-index.moralis.io/api/v2/erc20/{address}/price".format(
        address=WEB3_RSC_ADDRESS
    )
)


def editor_daily_payout_task():
    try:
        User = apps.get_model("user.User")
        today = datetime.date.today()
        num_days_this_month = monthrange(today.year, today.month)[1]
        gecko_result = get_daily_rsc_payout_amount_from_coin_gecko(num_days_this_month)
        moralis_result = get_daily_rsc_payout_amount_from_deep_index(num_days_this_month)
        result = gecko_result or moralis_result

        excluded_user_email = Gatekeeper.objects.filter(
            type__in=[EDITOR_PAYOUT_ADMIN, PAYOUT_EXCLUSION_LIST]
        ).values_list("email", flat=True)

        editors = (
            User.objects.filter(
                permissions__isnull=False,
                permissions__access_type=EDITOR,
                permissions__content_type=ContentType.objects.get_for_model(Hub),
            )
            .distinct()
            .exclude(email__in=(excluded_user_email))
        )

        from reputation.distributor import Distributor
        for editor in editors.iterator():
            try:
                pay_amount = result["pay_amount"]
                distributor = Distributor(
                    # this is NOT the model. It's a simple object
                    Distribution("EDITOR_PAYOUT", pay_amount, False),
                    editor,
                    None,
                    today,
                )
                distributor.distribute()

            except Exception as error:
                sentry.log_error(error)
                pass
    
        return result
    except Exception as error:
        sentry.log_error(error)


def get_daily_rsc_payout_amount_from_coin_gecko(num_days_this_month):
    recent_coin_gecko_rate = RscExchangeRate.objects.filter(
        price_source=COIN_GECKO,
        # greater than "TODAY" 2:50PM PST. Coin gecko prices are recorded every hr.
        # Current script should run at 3:10PM PST.
        created_date__gte=datetime.datetime.now().replace(hour=14, minute=50),
    ).first()

    if (recent_coin_gecko_rate is None):
        return None

    gecko_payout_usd_per_rsc = (
        recent_coin_gecko_rate.real_rate
        if recent_coin_gecko_rate.real_rate > USD_PER_RSC_PRICE_FLOOR
        else USD_PER_RSC_PRICE_FLOOR
    )

    return {
        "rate": recent_coin_gecko_rate.rate,
        "real_rate": recent_coin_gecko_rate.real_rate,
        "pay_amount": (USD_PAY_AMOUNT_PER_MONTH
            * math.pow(gecko_payout_usd_per_rsc, -1)
            / num_days_this_month
        ),
    }

def get_daily_rsc_payout_amount_from_deep_index(num_days_this_month):
    headers = requests.utils.default_headers()
    headers["x-api-key"] = MORALIS_API_KEY
    moralis_request_result = requests.get(MORALIS_LOOKUP_URI, headers=headers)

    real_usd_per_rsc = json.loads(moralis_request_result.text)["usdPrice"]
    payout_usd_per_rsc = (
        real_usd_per_rsc
        if real_usd_per_rsc > USD_PER_RSC_PRICE_FLOOR
        else USD_PER_RSC_PRICE_FLOOR
    )

    result = {
        "rate": payout_usd_per_rsc,
        "real_rate": real_usd_per_rsc,
        "pay_amount": (
            USD_PAY_AMOUNT_PER_MONTH
            * math.pow(payout_usd_per_rsc, -1)
            / num_days_this_month
        ),
    }

    # Keeping record of exchange rate used today
    RscExchangeRate.objects.create(
        rate=result["rate"],
        real_rate=result["real_rate"],
        target_currency=USD,
    )

    return result

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
    }""" % (
        WEB3_RSC_ADDRESS,
        UNI_SWAP_BUNDLE_ID,
    )

    request_result = requests.post(
        UNI_SWAP_GRAPH_URI, json={"query": uni_swap_query}, timeout=1
    )
    payload = json.loads(request_result.text).data

    eth_per_rsc = float(payload["rsc"]["derivedETH"])
    usd_per_eth = float(payload["bundle"]["ethPrice"])
    rsc_per_usd = math.pow((usd_per_eth * eth_per_rsc) or USD_PER_RSC_PRICE_FLOOR, -1)

    return USD_PAY_AMOUNT_PER_MONTH * rsc_per_usd / num_days_this_month
