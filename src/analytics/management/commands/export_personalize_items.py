"""
Django management command to export item data for AWS Personalize.

Usage:
    python manage.py export_personalize_items
    python manage.py export_personalize_items --start-date 2024-01-01
    python manage.py export_personalize_items --output /path/to/items.csv
"""

import os
from datetime import datetime
from time import time

from django.core.management.base import BaseCommand

from analytics.services.personalize_item_csv_builder import PersonalizeItemCSVBuilder
from analytics.services.personalize_item_utils import load_item_ids_from_interactions


class Command(BaseCommand):
    help = "Export item data to CSV for AWS Personalize"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date for filtering items (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date for filtering items (YYYY-MM-DD format)",
        )
        parser.add_argument(
            "--output",
            type=str,
            default=".tmp/personalize_items.csv",
            help="Output file path (default: .tmp/personalize_items.csv)",
        )
        parser.add_argument(
            "--filter-by-interactions",
            type=str,
            help=(
                "Path to interactions CSV file to filter items "
                "(exports only items with interactions)"
            ),
        )
        parser.add_argument(
            "--since",
            type=str,
            help=(
                "Include all papers created since this date (YYYY-MM-DD format). "
                "Existing filtering still applies to older papers."
            ),
        )

    def handle(self, *args, **options):
        start_time = time()
        start_datetime = datetime.now()

        start_date = options.get("start_date")
        end_date = options.get("end_date")
        output_path = options.get("output")
        interactions_path = options.get("filter_by_interactions")
        since_date = options.get("since")

        # Validate and parse dates if provided
        if start_date:
            try:
                start_date = datetime.strptime(start_date, "%Y-%m-%d")
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Invalid start-date format. Use YYYY-MM-DD.")
                )
                return

        if end_date:
            try:
                end_date = datetime.strptime(end_date, "%Y-%m-%d")
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Invalid end-date format. Use YYYY-MM-DD.")
                )
                return

        if since_date:
            try:
                since_date = datetime.strptime(since_date, "%Y-%m-%d")
            except ValueError:
                self.stdout.write(
                    self.style.ERROR("Invalid since format. Use YYYY-MM-DD.")
                )
                return

        # Load item IDs from interactions if filtering is requested
        item_ids = None
        if interactions_path:
            try:
                self.stdout.write(f"Loading item IDs from: {interactions_path}")
                item_ids = load_item_ids_from_interactions(interactions_path)
                self.stdout.write(
                    self.style.SUCCESS(f"Loaded {len(item_ids)} unique item IDs")
                )
            except FileNotFoundError as e:
                self.stdout.write(self.style.ERROR(str(e)))
                return
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error loading interactions: {e}"))
                return

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(
            f"Export started at: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.stdout.write(f"{'='*60}\n")

        self.stdout.write("Starting item export for AWS Personalize...")
        self.stdout.write(f"Output file: {output_path}")

        if start_date:
            self.stdout.write(f'Start date: {start_date.strftime("%Y-%m-%d")}')
        if end_date:
            self.stdout.write(f'End date: {end_date.strftime("%Y-%m-%d")}')
        if since_date:
            self.stdout.write(
                f'Since date: {since_date.strftime("%Y-%m-%d")} '
                f"(all papers created on or after this date will be included)"
            )
        if item_ids:
            self.stdout.write(f"Filtering by {len(item_ids)} items from interactions")

        # Build CSV
        builder = PersonalizeItemCSVBuilder()
        stats = builder.build_csv(
            output_path=output_path,
            start_date=start_date,
            end_date=end_date,
            item_ids=item_ids,
            since_date=since_date,
        )

        # Display statistics
        self.stdout.write(self.style.SUCCESS("\nExport completed!"))
        self.stdout.write(f'Total items exported: {stats["total_items"]}')
        if stats.get("filtered_by_interactions"):
            self.stdout.write("  (filtered by interactions)")
        self.stdout.write(f'Papers: {stats["papers"]}')
        self.stdout.write(f'Posts: {stats["posts"]}')

        self.stdout.write("\nBreakdown by document type:")
        for doc_type, count in stats["by_type"].items():
            self.stdout.write(f"  {doc_type}: {count}")

        # Display file size
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            file_size_mb = file_size / (1024 * 1024)
            self.stdout.write(
                f"\nFile size: {file_size_mb:.2f} MB ({file_size:,} bytes)"
            )

        # Display timing metrics
        end_time = time()
        end_datetime = datetime.now()
        duration = end_time - start_time

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(
            f"Export ended at: {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.stdout.write(
            f"Total duration: {duration:.2f} seconds ({duration/60:.2f} minutes)"
        )
        if stats["total_items"] > 0:
            items_per_sec = stats["total_items"] / duration
            self.stdout.write(
                f"Average speed: {items_per_sec:.2f} items/second "
                f"({(duration/stats['total_items'])*1000:.2f} ms/item)"
            )
        self.stdout.write(f"{'='*60}")
