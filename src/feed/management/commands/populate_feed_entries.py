from datetime import datetime

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from feed.tasks import serialize_feed_item


class Command(BaseCommand):
    help = "Populates metrics and content for feed entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            default=False,
            help="Process all feed entries, not just those with empty fields.",
        )
        parser.add_argument(
            "--metrics-only",
            action="store_true",
            default=False,
            help="Only update metrics (not content).",
        )
        parser.add_argument(
            "--content-only",
            action="store_true",
            default=False,
            help="Only update content (not metrics).",
        )
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only process entries with action_date after this date (YYYY-MM-DD). Overrides existing data.",
        )
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Process a specific FeedEntry by ID (overrides existing data).",
        )

    def handle(self, *args, **options):
        queryset = FeedEntry.objects.all()
        entry_id = options.get("id")

        # If specific ID provided, filter to just that entry (overrides other filters)
        if entry_id:
            queryset = queryset.filter(id=entry_id)
            if not queryset.exists():
                self.stderr.write(
                    self.style.ERROR(f"FeedEntry with ID {entry_id} not found.")
                )
                return
            self.stdout.write(f"Processing specific entry ID: {entry_id}")
        else:
            # Apply --since filter
            if options["since"]:
                try:
                    since_dt = datetime.strptime(options["since"], "%Y-%m-%d")
                    since_dt = timezone.make_aware(since_dt)
                    queryset = queryset.filter(action_date__gte=since_dt)
                    self.stdout.write(
                        f"Filtering entries with action_date since {options['since']}"
                    )
                except ValueError:
                    self.stderr.write(
                        self.style.ERROR("Invalid date format. Use YYYY-MM-DD.")
                    )
                    return

        # Apply empty field filter unless --all, --id, or --since (these override existing data)
        metrics_only = options["metrics_only"]
        content_only = options["content_only"]
        update_both = not metrics_only and not content_only

        if not options["all"] and not entry_id and not options["since"]:
            if metrics_only:
                queryset = queryset.filter(metrics={})
            elif content_only:
                queryset = queryset.filter(content={})
            else:
                queryset = queryset.filter(Q(metrics={}) | Q(content={}))

        queryset = queryset.order_by("-id")
        total = queryset.count()
        self.stdout.write(f"Processing {total} entries")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No entries to process"))
            return

        processed = 0
        errors = 0

        qs = queryset.select_related("content_type", "unified_document")
        for entry in qs.iterator(chunk_size=1000):
            try:
                if not entry.item:
                    continue

                fields_to_update = []

                if metrics_only or update_both:
                    entry.metrics = serialize_feed_metrics(
                        entry.item, entry.content_type
                    )
                    fields_to_update.append("metrics")

                if content_only or update_both:
                    entry.content = serialize_feed_item(entry.item, entry.content_type)
                    fields_to_update.append("content")

                if entry.unified_document:
                    entry.hot_score_v2 = entry.calculate_hot_score_v2()
                    fields_to_update.append("hot_score_v2")

                entry.save(update_fields=fields_to_update)
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(self.style.ERROR(f"Error on entry {entry.id}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(f"Done: processed={processed}, errors={errors}")
        )
