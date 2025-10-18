"""
Management command to backfill hot_score_v2 for existing feed entries.

This command efficiently calculates and updates hot_score_v2 for entries
matching specified criteria (date range, content type).

Usage:
    # Backfill all papers
    python manage.py backfill_hot_score_v2 --content-type paper

    # Backfill all posts
    python manage.py backfill_hot_score_v2 --content-type post

    # Backfill papers created in last 30 days
    python manage.py backfill_hot_score_v2 --content-type paper --days 30

    # Backfill specific date range
    python manage.py backfill_hot_score_v2 --start-date 2024-01-01 --end-date 2024-12-31

    # Backfill everything
    python manage.py backfill_hot_score_v2 --all

    # Backfill specific unified document(s)
    python manage.py backfill_hot_score_v2 --unified-document-id 12345
    python manage.py backfill_hot_score_v2 --unified-document-ids 12345 67890 11111

    # Dry run (show what would be updated)
    python manage.py backfill_hot_score_v2 --content-type paper --dry-run
"""

import logging
from datetime import datetime, timedelta

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from paper.related_models.paper_model import Paper
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Backfill hot_score_v2 for existing feed entries with filtering"

    def add_arguments(self, parser):
        parser.add_argument(
            "--content-type",
            type=str,
            choices=["paper", "post", "all"],
            help="Filter by content type (paper, post, or all)",
        )
        parser.add_argument(
            "--days",
            type=int,
            help="Only process entries created in last N days",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date (YYYY-MM-DD) for filtering by created_date",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date (YYYY-MM-DD) for filtering by created_date",
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
            "--all",
            action="store_true",
            help="Process all feed entries (ignore filters)",
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
        content_type_filter = options.get("content_type")
        days = options.get("days")
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        process_all = options["all"]
        unified_document_id = options.get("unified_document_id")
        unified_document_ids = options.get("unified_document_ids")

        self.stdout.write(self.style.SUCCESS("Hot Score V2 Backfill Tool"))
        self.stdout.write("=" * 80)

        # Build queryset
        queryset = FeedEntry.objects.select_related(
            "content_type", "unified_document"
        ).prefetch_related("item")

        # Apply content type filter
        if not process_all and content_type_filter:
            if content_type_filter == "paper":
                paper_ct = ContentType.objects.get_for_model(Paper)
                queryset = queryset.filter(content_type=paper_ct)
            elif content_type_filter == "post":
                post_ct = ContentType.objects.get_for_model(ResearchhubPost)
                queryset = queryset.filter(content_type=post_ct)

        # Apply date filters
        if not process_all:
            if days:
                cutoff_date = timezone.now() - timedelta(days=days)
                queryset = queryset.filter(created_date__gte=cutoff_date)
            elif start_date or end_date:
                if start_date:
                    start = datetime.strptime(start_date, "%Y-%m-%d")
                    start = timezone.make_aware(start)
                    queryset = queryset.filter(created_date__gte=start)
                if end_date:
                    end = datetime.strptime(end_date, "%Y-%m-%d")
                    end = timezone.make_aware(end)
                    queryset = queryset.filter(created_date__lte=end)

        # Apply unified document ID filter
        if not process_all:
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
        if process_all:
            self.stdout.write(self.style.WARNING("Processing ALL feed entries"))
        else:
            filters = []
            if content_type_filter:
                filters.append(f"Type: {content_type_filter}")
            if days:
                filters.append(f"Last {days} days")
            if start_date:
                filters.append(f"From: {start_date}")
            if end_date:
                filters.append(f"To: {end_date}")

            # Show unified document ID filter
            doc_ids = []
            if unified_document_id:
                doc_ids.append(unified_document_id)
            if unified_document_ids:
                doc_ids.extend(unified_document_ids)
            if doc_ids:
                filters.append(f"Unified Doc IDs: {', '.join(map(str, doc_ids))}")

            self.stdout.write(f"Filters: {', '.join(filters) if filters else 'None'}")

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

        # Use shared batch processing function
        from feed.tasks import refresh_feed_hot_scores_batch

        # Pass the pre-filtered queryset (respects all user filters)
        stats = refresh_feed_hot_scores_batch(
            queryset=queryset,
            batch_size=batch_size,
            update_v1=False,  # Only update v2 in backfill
            update_v2=True,
            days_back=None,  # Ignored when queryset is provided
            content_types=None,  # Ignored when queryset is provided
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
        self.stdout.write(f"{'ID':<10} {'Type':<15} {'Title':<40} {'Created':<12}")
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
            title = title[:37] + "..." if len(title) > 40 else title

            item_type = entry.content_type.model
            created = entry.created_date.strftime("%Y-%m-%d")

            self.stdout.write(
                f"{entry.id:<10} {item_type:<15} {title:<40} {created:<12}"
            )

        self.stdout.write("")
        self.stdout.write(
            f"... and {queryset.count() - 10:,} more entries"
            if queryset.count() > 10
            else ""
        )
