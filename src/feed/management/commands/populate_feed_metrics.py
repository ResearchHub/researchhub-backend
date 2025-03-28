from django.core.management.base import BaseCommand

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics

CHUNK_SIZE = 1000


class Command(BaseCommand):
    help = "Populates metrics for feed entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            dest="all",
            default=False,
            help="Populate metrics for all feed entries, not just those with empty metrics.",
        )

    def handle(self, *args, **options):
        process_all = options["all"]

        queryset = FeedEntry.objects

        if not process_all:
            print("Filtering feed entries with empty metrics...")
            queryset = queryset.filter(metrics={})

        for feed_entry in queryset.iterator(chunk_size=CHUNK_SIZE):
            feed_item = feed_entry.item
            print(f"Saving metrics for feed entry: {feed_entry.id}")
            metrics = serialize_feed_metrics(feed_item, feed_entry.content_type)
            feed_entry.metrics = metrics
            feed_entry.save(update_fields=["metrics"])
