from celery.task.schedules import crontab
from celery.decorators import periodic_task
from django.contrib.contenttypes.models import ContentType

from researchhub.celery import app
from mailing_list.lib import base_email_context
from purchase.models import Purchase, Support
from researchhub.settings import APP_ENV
from paper.utils import invalidate_trending_cache
from utils.message import send_email_message


@periodic_task(
    run_every=crontab(hour='*/2'),
    priority=2,
    options={'queue': APP_ENV}
)
def update_purchases():
    PAPER_CONTENT_TYPE = ContentType.objects.get(app_label='paper', model='paper')
    purchases = Purchase.objects.filter(boost_time__gt=0)
    for purchase in purchases:
        purchase.boost_time = purchase.get_boost_time()
        purchase.save()

        if purchase.content_type == PAPER_CONTENT_TYPE:
            paper = PAPER_CONTENT_TYPE.get_object_for_this_type(
                id=purchase.object_id
            )
            paper.calculate_hot_score()

    hub_ids = []
    invalidate_trending_cache(hub_ids)


@app.task
def send_support_email(profile_url, sender_name, recipient_name, email, amount, date, payment_type, email_type, paper_data):
    if payment_type == Support.STRIPE:
        payment_type = 'Stripe'
    elif payment_type == Support.PAYPAL:
        payment_type = 'Paypal'
    elif payment_type == Support.ETH:
        payment_type = 'Ethereum'
    elif payment_type == Support.BTC:
        payment_type = 'Bitcoin'
    elif payment_type == Support.RSC_ON_CHAIN:
        payment_type = 'ResearchHub Coin'
    elif payment_type == Support.RSC_OFF_CHAIN:
        payment_type = 'ResearchHub Coin'

    context = {
        **base_email_context,
        'amount': amount,
        'date': date,
        'method': payment_type,
        'email': email,
        'recipient': email_type == 'recipient',
        'sender_name': sender_name,
        'recipient_name': recipient_name,
        'paper': paper_data,
        'user_profile': profile_url,
    }

    if email_type == 'sender':
        subject = 'Receipt From ResearchHub'
        send_email_message(
            email,
            'support_receipt.txt',
            subject,
            context,
            html_template='support_receipt.html'
        )
    elif email_type == 'recipient':
        subject = 'Support From ResearchHub'
        send_email_message(
            email,
            'support_receipt.txt',
            subject,
            context,
            html_template='support_receipt.html'
        )
