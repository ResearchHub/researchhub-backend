from celery.task.schedules import crontab
from celery.decorators import periodic_task
from django.contrib.contenttypes.models import ContentType

from paper.models import Paper
from researchhub.celery import app
from mailing_list.lib import base_email_context
from purchase.models import Purchase, Support
from researchhub.settings import APP_ENV, BASE_FRONTEND_URL
from paper.utils import invalidate_trending_cache, reset_cache
from utils.message import send_email_message


@periodic_task(
    run_every=crontab(minute='*/30'),
    priority=2,
    options={'queue': APP_ENV}
)
def update_purchases():
    PAPER_CONTENT_TYPE = ContentType.objects.get(
        app_label='paper',
        model='paper'
    )
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
    context = {}
    reset_cache(hub_ids, context, {})


@app.task
def send_support_email(
    profile_url,
    sender_name,
    recipient_name,
    email,
    amount,
    date,
    payment_type,
    email_type,
    content_type,
    object_id
):

    paper_data = {}
    object_supported = 'profile'
    if content_type == 'paper':
        paper = Paper.objects.get(id=object_id)
        paper_data['title'] = paper.title
        paper_summary = f'From Paper: {paper.summary}' if paper.summary else ''
        paper_data['summary'] = paper_summary
        paper_data['uploaded_by'] = paper.uploaded_by.full_name()
        paper_data['discussion_count'] = paper.discussion_count
        paper_data['paper_type'] = ''.join(
            paper.paper_type.split('_')
        ).capitalize()
        paper_data['url'] = f'{BASE_FRONTEND_URL}/paper/{paper.id}/{paper.slug}'
        object_supported = 'paper'
    elif content_type == 'thread':
        object_supported = 'thread'
    elif content_type == 'comment':
        object_supported = 'comment'
    elif content_type == 'reply':
        object_supported = 'reply'
    elif content_type == 'summary':
        object_supported = 'summary'
    elif content_type == 'bulletpoint':
        object_supported = 'key takeaway'

    if payment_type == Support.STRIPE:
        payment_type = 'USD'
    elif payment_type == Support.PAYPAL:
        payment_type = 'Paypal'
    elif payment_type == Support.ETH:
        payment_type = 'Ethereum'
    elif payment_type == Support.BTC:
        payment_type = 'Bitcoin'
    elif payment_type in Support.RSC_ON_CHAIN:
        payment_type = 'ResearchCoin'
    elif payment_type in Support.RSC_OFF_CHAIN:
        payment_type = 'ResearchCoin'

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
        'object_supported': object_supported
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
