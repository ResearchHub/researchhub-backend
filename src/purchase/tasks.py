from celery.task.schedules import crontab
from celery.decorators import periodic_task

from purchase.models import Purchase
from researchhub.settings import APP_ENV
from paper.utils import invalidate_trending_cache


@periodic_task(
    run_every=crontab(hour='*/2'),
    priority=2,
    options={'queue': APP_ENV}
)
def update_purchases():
    purchases = Purchase.objects.filter(boost_time__gt=0)
    for purchase in purchases:
        purchase_boost_time = purchase.get_boost_time()
        purchase.boost_time = purchase_boost_time
        purchase.save()

    hub_ids = []
    invalidate_trending_cache(hub_ids)
