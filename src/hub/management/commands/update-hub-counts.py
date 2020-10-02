from django.core.management.base import BaseCommand
from django.db.models import Sum
from hub.models import Hub


class Command(BaseCommand):

    def handle(self, *args, **options):
        all_hubs = Hub.objects.all()
        for hub in all_hubs:
            print('calculating subscriber_count for', hub.name)
            hub.subscriber_count = hub.subscribers.count()
            print('calculating paper_count for', hub.name)
            hub.paper_count = hub.papers.count()
            print('calculating discussion_count for', hub.name)
            annotation = Hub.objects.filter(id=hub.id).annotate(hub_discussion_count=Sum('papers__discussion_count'))
            hub.discussion_count = annotation.first().hub_discussion_count or 0
            hub.save()
