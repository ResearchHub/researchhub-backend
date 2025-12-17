"""
Management command to backfill hot_score_v2 for existing paper feed entries.

This command efficiently calculates and updates hot_score_v2 for paper entries
matching specified criteria (date range based on paper_publish_date).

Usage:
    # Backfill all papers
    python manage.py backfill_hot_score_v2

    # Backfill papers published in last 30 days
    python manage.py backfill_hot_score_v2 --days 30

    # Backfill specific date range (uses paper_publish_date)
    python manage.py backfill_hot_score_v2 --start-date 2024-01-01 --end-date 2024-12-31

    # Backfill specific unified document(s)
    python manage.py backfill_hot_score_v2 --unified-document-id 12345
    python manage.py backfill_hot_score_v2 --unified-document-ids 12345 67890 11111

    # Dry run (show what would be updated)
    python manage.py backfill_hot_score_v2 --dry-run
"""

import logging
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import refresh_feed_hot_scores_batch
from paper.related_models.paper_model import Paper

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill hot_score_v2 for existing paper feed entries"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            help="Only process papers published in last N days",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date (YYYY-MM-DD) for filtering by paper_publish_date",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date (YYYY-MM-DD) for filtering by paper_publish_date",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of entries to process per batch (default: 1000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be updated without making changes",
        )
        parser.add_argument(
            "--unified-document-id",
            type=int,
            help="Process entries for a specific unified document ID",
        )
        parser.add_argument(
            "--unified-document-ids",
            type=int,
            nargs="+",
            help="Process entries for multiple unified document IDs",
        )

    def handle(self, *args, **options):
        days = options.get("days")
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        unified_document_id = options.get("unified_document_id")
        unified_document_ids = options.get("unified_document_ids")

        self.stdout.write(
            self.style.SUCCESS("Hot Score V2 Backfill Tool (Papers Only)")
        )
        self.stdout.write("=" * 80)

        # Build queryset - only papers
        paper_ct = ContentType.objects.get_for_model(Paper)
        queryset = (
            FeedEntry.objects.select_related("content_type", "unified_document")
            .prefetch_related("item")
            .filter(content_type=paper_ct)
        )

        # Apply date filters using paper_publish_date
        if days:
            cutoff_date = timezone.now() - timedelta(days=days)
            paper_ids = Paper.objects.filter(
                paper_publish_date__gte=cutoff_date
            ).values("id")
            queryset = queryset.filter(object_id__in=paper_ids)
        elif start_date or end_date:
            paper_filter = {}
            if start_date:
                start = datetime.strptime(start_date, "%Y-%m-%d")
                start = timezone.make_aware(start)
                paper_filter["paper_publish_date__gte"] = start
            if end_date:
                end = datetime.strptime(end_date, "%Y-%m-%d")
                end = timezone.make_aware(end)
                paper_filter["paper_publish_date__lte"] = end
            if paper_filter:
                paper_ids = Paper.objects.filter(**paper_filter).values("id")
                queryset = queryset.filter(object_id__in=paper_ids)

        # Apply unified document ID filter
        doc_ids = []
        if unified_document_id:
            doc_ids.append(unified_document_id)
        if unified_document_ids:
            doc_ids.extend(unified_document_ids)

        if doc_ids:
            queryset = queryset.filter(unified_document_id__in=doc_ids)

        total_count = queryset.count()

        # Display what will be processed
        self.stdout.write("")
        filters = ["Content type: paper"]
        if days:
            filters.append(f"Published in last {days} days")
        if start_date:
            filters.append(f"Published from: {start_date}")
        if end_date:
            filters.append(f"Published to: {end_date}")
        if doc_ids:
            filters.append(f"Unified Doc IDs: {', '.join(map(str, doc_ids))}")

        self.stdout.write(f"Filters: {', '.join(filters)}")

        self.stdout.write(f"Total entries to process: {total_count:,}")
        self.stdout.write(f"Batch size: {batch_size}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n⚠️  DRY RUN MODE - No changes will be made")
            )
            self.stdout.write("")
            self._show_sample(queryset)
            return

        # Confirm before proceeding
        self.stdout.write("")
        confirm = input("Proceed with backfill? This may take a while. [y/N]: ")
        if confirm.lower() != "y":
            self.stdout.write(self.style.WARNING("Cancelled."))
            return

        # Process using shared batch processing function
        self.stdout.write("")
        self.stdout.write("Processing entries...")

        # Define progress callback for CLI feedback
        def progress_callback(processed, total, updated, errors):
            pct = (processed / total) * 100 if total > 0 else 0
            self.stdout.write(
                f"  Progress: {processed:,}/{total:,} ({pct:.1f}%) - "
                f"Updated: {updated:,}, Errors: {errors}",
                ending="\r",
            )

        # Pass the pre-filtered queryset (respects all user filters)
        stats = refresh_feed_hot_scores_batch(
            queryset=queryset,
            batch_size=batch_size,
            days_back=None,
            content_types=None,
            progress_callback=progress_callback,
        )

        processed = stats["processed"]
        updated = stats["updated"]
        errors = stats["errors"]
        duration = stats["duration"]
        self.stdout.write("")
        self.stdout.write("")
        self.stdout.write("=" * 80)
        self.stdout.write(self.style.SUCCESS("✓ Backfill Complete"))
        self.stdout.write("")
        self.stdout.write(f"  Total processed: {processed:,}")
        self.stdout.write(f"  Successfully updated: {updated:,}")
        self.stdout.write(f"  Errors: {errors}")
        self.stdout.write(f"  Duration: {duration:.1f} seconds")
        self.stdout.write(f"  Rate: {processed/duration:.1f} entries/second")

        if errors > 0:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"⚠️  {errors} entries had errors. " "Check logs for details."
                )
            )

    def _show_sample(self, queryset):
        """Show a sample of what would be updated."""
        self.stdout.write("Sample of entries that would be updated:")
        self.stdout.write("-" * 80)
        self.stdout.write(f"{'ID':<10} {'Title':<45} {'Published':<12}")
        self.stdout.write("-" * 80)

        sample = queryset[:10]
        for entry in sample:
            if not entry.item:
                continue

            item = entry.item
            title = getattr(item, "title", "")
            if not title:
                title = getattr(item, "paper_title", "")
            if not title:
                title = f"Entry #{entry.id}"
            title = title[:42] + "..." if len(title) > 45 else title

            publish_date = getattr(item, "paper_publish_date", None)
            published = publish_date.strftime("%Y-%m-%d") if publish_date else "N/A"

            self.stdout.write(f"{entry.id:<10} {title:<45} {published:<12}")

        self.stdout.write("")
        self.stdout.write(
            f"... and {queryset.count() - 10:,} more entries"
            if queryset.count() > 10
            else ""
        )
