from django.core.management.base import BaseCommand
from django.db.models import Q

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from feed.tasks import serialize_feed_item

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
        parser.add_argument(
            "--metrics-only",
            action="store_true",
            dest="metrics_only",
            default=False,
            help="Whether to only populate metrics for feed entries.",
        )
        parser.add_argument(
            "--content-only",
            action="store_true",
            dest="content_only",
            default=False,
            help="Whether to only populate object content for feed entries.",
        )

    def handle(self, *args, **options):
        process_all = options["all"]
        metrics_only = options["metrics_only"]
        content_only = options["content_only"]
        update_both = not metrics_only and not content_only

        queryset = FeedEntry.objects

        if not process_all:
            empty_fields_filter = Q()

            if metrics_only:
                print("Filtering entries with empty metrics")
                empty_fields_filter = Q(metrics={})
            elif content_only:
                print("Filtering entries with empty content")
                empty_fields_filter = Q(content={})
            else:
                print("Filtering entries with either empty metrics or empty content")
                empty_fields_filter = Q(metrics={}) | Q(content={})

            queryset = queryset.filter(empty_fields_filter)

        for feed_entry in queryset.iterator(chunk_size=CHUNK_SIZE):
            feed_item = feed_entry.item
            fields_to_update = []

            if metrics_only or update_both:
                metrics = serialize_feed_metrics(feed_item, feed_entry.content_type)
                feed_entry.metrics = metrics
                fields_to_update.append("metrics")

            if content_only or update_both:
                content = serialize_feed_item(feed_item, feed_entry.content_type)
                feed_entry.content = content
                fields_to_update.append("content")

            print(
                f"Populating feed entry: {feed_entry.id} ({', '.join(fields_to_update)})"
            )
            feed_entry.save(update_fields=fields_to_update)
