from calendar import monthrange
from io import StringIO
import csv
import datetime
import json
import math
import requests

from celery.decorators import periodic_task
from celery.task.schedules import crontab
from django.contrib.contenttypes.models import ContentType
from django.core.mail import EmailMessage
from django.core.mail import EmailMessage

from hub.models import Hub
from reputation.distributor import Distributor
from reputation.distributions import Distribution  # this is NOT the model
from researchhub_access_group.constants import EDITOR
from purchase.related_models.constants.rsc_exchange_currency import USD
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from researchhub.settings import  MORALIS_API_KEY, PAYOUT_ADMINS, PAYOUT_EXCLUSION_LIST, WEB3_RSC_ADDRESS
from user.related_models.user_model import User
from utils import sentry

UNI_SWAP_BUNDLE_ID = 1  # their own hard-coded eth-bundle id
UNI_SWAP_GRAPH_URI = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v2"
USD_PAY_AMOUNT_PER_MONTH = 3000
USD_PER_RSC_PRICE_FLOOR = .033

MORALIS_LOOKUP_URI = "https://deep-index.moralis.io/api/v2/erc20/{address}/price".format(address=WEB3_RSC_ADDRESS)


# @periodic_task(
#     run_every=crontab(hour=15, minute=0),  # 3PM System Time (PST)
#     priority=1,
#     options={'queue': f'{APP_ENV}_core_queue'}
# )
def editor_daily_payout_task():
    today = datetime.date.today()
    num_days_this_month = monthrange(today.year, today.month)[1]
    result = get_daily_rsc_payout_amount_from_deep_index(num_days_this_month)

    # Keeping record of exchange rate used today
    RscExchangeRate.objects.create(
      rate=result['rate'],
      target_currency=USD,
    )

    editors = User.objects.filter(
        permissions__isnull=False,
        permissions__access_type=EDITOR,
        permissions__content_type=ContentType.objects.get_for_model(Hub)
    ).distinct().exclude(email__in=(PAYOUT_EXCLUSION_LIST))

    csv_prep = {
      'amount-rsc': [],
      'emails': [],
      'names': [],
      'usd-rsc-rate': [],
    }

    for editor in editors.iterator():
        try:
            pay_amount = result['pay_amount']
            distributor = Distributor(
                  # this is NOT the model. It's a simple object
                  Distribution('EDITOR_PAYOUT', pay_amount, False),
                  editor,
                  None,
                  today
              )
            distributor.distribute()

            csv_prep['names'].append(
                editor.first_name or "" + editor.last_name or ""
            )
            csv_prep['emails'].append(editor.email)
            csv_prep['amount-rsc'].append(pay_amount)

        except Exception as error:
            sentry.log_error(error)
            print('error: ', error)
            pass
    try:
        today_iso = today.strftime('YYYY-MM-DD')
        title = f'Editor Payout {today_iso}'
        csv_file = StringIO()
        csv_writer = csv.DictWriter(
          csv_file,
          # logical ordering
          fieldnames=['names', 'emails', 'amount-rsc', 'usd-rsc-rate']
        )
        csv_writer.writeheader()

        prepped_rows = []
        for index in range(editors.count()):
            prepped_rows.append({
                'names': csv_prep['names'][index],
                'emails': csv_prep['emails'][index],
                'amount-rsc': csv_prep['amount-rsc'][index],
                'usd-rsc-rate': result['rate'],
            })

        csv_writer.writerows(prepped_rows)
        email = EmailMessage(
            subject=title,
            body=f'Editor payout csv - {today_iso}',
            from_email='ResearchHub <noreply@researchhub.com>',
            to=PAYOUT_ADMINS,
        )
        email.attach(f'{title}.csv', csv_file.getvalue(), 'text/csv')
        email.send()

    except Exception as error:
        sentry.log_error(error)
        print('error: ', error)
        pass


def get_daily_rsc_payout_amount_from_deep_index(num_days_this_month):
    headers = requests.utils.default_headers()
    headers['x-api-key'] = MORALIS_API_KEY
    request_result = requests.get(
        MORALIS_LOOKUP_URI,
        headers=headers
    )
    real_usd_per_rsc = json.loads(request_result.text)['usdPrice']
    payout_usd_per_rsc = real_usd_per_rsc if \
        real_usd_per_rsc > USD_PER_RSC_PRICE_FLOOR \
        else USD_PER_RSC_PRICE_FLOOR
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
        json={'query': uni_swap_query},
        timeout=1
    )
    payload = json.loads(request_result.text).data

    eth_per_rsc = float(payload['rsc']['derivedETH'])
    usd_per_eth = float(payload['bundle']['ethPrice'])
    rsc_per_usd = math.pow(
        (usd_per_eth * eth_per_rsc) or USD_PER_RSC_PRICE_FLOOR,
        -1
    )

    return (
      USD_PAY_AMOUNT_PER_MONTH * rsc_per_usd / num_days_this_month
    )
