from django.core.management.base import BaseCommand
from hub.models import Hub


class Command(BaseCommand):

    def handle(self, *args, **options):
        all_hubs = Hub.objects.all()
        for hub in all_hubs:
            hub.paper_count = hub.papers.count()
            hub.discussion_count = sum(paper.discussion_count_indexing for paper in hub.papers.all())
            hub.save()
