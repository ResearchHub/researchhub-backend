from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db.models import Q

from feed.hot_score import calculate_hot_score
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
        parser.add_argument(
            "--use-old-hot-score-calculation",
            action="store_true",
            dest="use_old_hot_score_calculation",
            default=False,
            help="Whether to use the old hot score calculation.",
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

        # Order by ID in descending order to process the most recent entries first
        queryset = queryset.order_by("-id")

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

            # Update hot score for papers and posts
            if feed_entry.unified_document:
                if options["use_old_hot_score_calculation"]:
                    feed_entry.hot_score = feed_item.unified_document.hot_score
                else:
                    feed_entry.hot_score = calculate_hot_score(feed_item)

                fields_to_update.append("hot_score")

            print(
                f"Populating feed entry: {feed_entry.id} ({', '.join(fields_to_update)})"
            )
            feed_entry.save(update_fields=fields_to_update)
