import datetime
import logging
import math
from calendar import monthrange

from django.apps import apps
from django.db.models import F

from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution  # this is NOT the model
from reputation.related_models.distribution import Distribution as DistributionModel
from researchhub_access_group.constants import (
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from user.constants.gatekeeper_constants import (
    EDITOR_PAYOUT_ADMIN,
    PAYOUT_EXCLUSION_LIST,
)
from user.related_models.gatekeeper_model import Gatekeeper

logger = logging.getLogger(__name__)

# TODO: calvinhlee consider moving these to ENV variable
ASSISTANT_EDITOR_USD_PAY_AMOUNT_PER_MONTH = 1000
ASSOCIATE_EDITOR_USD_PAY_AMOUNT_PER_MONTH = 1500
SENIOR_EDITOR_USD_PAY_AMOUNT_PER_MONTH = 2000
USD_PER_RSC_PRICE_FLOOR = 0.10


def editor_daily_payout_task():
    try:
        is_payment_made_today = DistributionModel.objects.filter(
            distribution_type="EDITOR_PAYOUT",
            created_date__gte=datetime.datetime.now().replace(hour=0, minute=0),
        ).exists()
        if is_payment_made_today:
            return {"msg": "Editor payout already made today"}

        User = apps.get_model("user.User")  # noqa: N806
        today = datetime.date.today()
        num_days_this_month = monthrange(today.year, today.month)[1]
        result = get_daily_rsc_payout_amount_from_coin_gecko(num_days_this_month)
        if result is None:
            logger.warning("Skipping editor payouts: no recent CoinGecko rate")
            return None

        excluded_user_email = Gatekeeper.objects.filter(
            type__in=[EDITOR_PAYOUT_ADMIN, PAYOUT_EXCLUSION_LIST]
        ).values_list("email", flat=True)

        editors = (
            User.objects.editors()
            .exclude(email__in=(excluded_user_email))
            .annotate(editor_type=F("permissions__access_type"))
        )

        from reputation.distributor import Distributor

        for editor in editors.iterator():
            try:
                editor_type = editor.editor_type
                if editor_type == SENIOR_EDITOR:
                    pay_amount = result["senior_pay_amount"]
                elif editor_type == ASSOCIATE_EDITOR:
                    pay_amount = result["associate_pay_amount"]
                else:
                    pay_amount = result["assistant_pay_amount"]

                distributor = Distributor(
                    # this is NOT the model. It's a simple object
                    Distribution("EDITOR_PAYOUT", pay_amount, False),
                    editor,
                    None,
                    today,
                )
                distributor.distribute()

            except Exception:
                logger.exception("Failed to distribute payout to editor %s", editor.id)

        return result
    except Exception:
        logger.exception("Failed to execute editor daily payout task")


def get_daily_rsc_payout_amount_from_coin_gecko(num_days_this_month):
    recent_coin_gecko_rate = RscExchangeRate.objects.filter(
        price_source=COIN_GECKO,
        # greater than "TODAY" 2:50PM PST. Coin gecko prices are recorded every hr.
        # Current script should run at 3:02PM PST.
        created_date__gte=datetime.datetime.now().replace(hour=14, minute=50),
    ).first()

    if recent_coin_gecko_rate is None:
        return None

    gecko_payout_usd_per_rsc = max(
        USD_PER_RSC_PRICE_FLOOR, recent_coin_gecko_rate.real_rate
    )

    return {
        "rate": recent_coin_gecko_rate.rate,
        "real_rate": recent_coin_gecko_rate.real_rate,
        "assistant_pay_amount": (
            ASSISTANT_EDITOR_USD_PAY_AMOUNT_PER_MONTH
            * math.pow(gecko_payout_usd_per_rsc, -1)
            / num_days_this_month
        ),
        "associate_pay_amount": (
            ASSOCIATE_EDITOR_USD_PAY_AMOUNT_PER_MONTH
            * math.pow(gecko_payout_usd_per_rsc, -1)
            / num_days_this_month
        ),
        "senior_pay_amount": (
            SENIOR_EDITOR_USD_PAY_AMOUNT_PER_MONTH
            * math.pow(gecko_payout_usd_per_rsc, -1)
            / num_days_this_month
        ),
    }
