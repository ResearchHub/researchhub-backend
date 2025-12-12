"""
Backfill pdf_copyright_allows_display for existing feed entries.

Usage:
    python manage.py backfill_pdf_copyright
    python manage.py backfill_pdf_copyright --since 2024-01-01
"""

import logging
import time
from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from paper.utils import pdf_copyright_allows_display

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill pdf_copyright_allows_display for existing feed entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            help="Process entries with action_date >= this date (YYYY-MM-DD)",
        )

    def handle(self, *args, **options):
        since = options.get("since")
        batch_size = 1000

        queryset = FeedEntry.objects.select_related("content_type").prefetch_related(
            "item"
        )

        if since:
            since_date = timezone.make_aware(datetime.strptime(since, "%Y-%m-%d"))
            queryset = queryset.filter(action_date__gte=since_date)

        paper_ct = ContentType.objects.get_for_model(Paper)
        total = queryset.count()

        self.stdout.write(f"Processing {total:,} entries...")

        start_time = time.time()
        updated = 0
        set_to_false = 0
        errors = 0

        for offset in range(0, total, batch_size):
            batch = list(queryset[offset : offset + batch_size])
            entries_to_update = []

            for entry in batch:
                try:
                    if entry.content_type_id == paper_ct.id and entry.item:
                        allows = pdf_copyright_allows_display(entry.item)
                        if not allows:
                            set_to_false += 1
                    else:
                        allows = True

                    entry.pdf_copyright_allows_display = allows
                    entries_to_update.append(entry)
                except Exception as e:
                    errors += 1
                    logger.error(f"Error processing entry {entry.id}: {e}")

            if entries_to_update:
                FeedEntry.objects.bulk_update(
                    entries_to_update,
                    ["pdf_copyright_allows_display"],
                    batch_size=batch_size,
                )
                updated += len(entries_to_update)

            self.stdout.write(f"  {updated:,}/{total:,}", ending="\r")

        duration = time.time() - start_time
        self.stdout.write(
            f"\nDone: {updated:,} updated, {set_to_false:,} set to False, "
            f"{errors} errors, {duration:.1f}s"
        )
