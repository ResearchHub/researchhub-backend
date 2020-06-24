from celery.task.schedules import crontab
from celery.decorators import periodic_task
from django.contrib.contenttypes.models import ContentType

from purchase.models import Purchase
from researchhub.settings import APP_ENV
from paper.utils import invalidate_trending_cache

PAPER_CONTENT_TYPE = ContentType.objects.get(app_label='paper', model='paper')


@periodic_task(
    run_every=crontab(hour='*/2'),
    priority=2,
    options={'queue': APP_ENV}
)
def update_purchases():
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
