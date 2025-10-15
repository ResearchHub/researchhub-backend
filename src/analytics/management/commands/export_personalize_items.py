"""
Django management command to export item data for AWS Personalize.

Usage:
    python manage.py export_personalize_items
    python manage.py export_personalize_items --start-date 2024-01-01
    python manage.py export_personalize_items --output /path/to/items.csv
"""

import os
from datetime import datetime

from django.core.management.base import BaseCommand

from analytics.services.personalize_item_csv_builder import PersonalizeItemCSVBuilder


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

    def handle(self, *args, **options):
        start_date = options.get("start_date")
        end_date = options.get("end_date")
        output_path = options.get("output")

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

        self.stdout.write("Starting item export for AWS Personalize...")
        self.stdout.write(f"Output file: {output_path}")

        if start_date:
            self.stdout.write(f'Start date: {start_date.strftime("%Y-%m-%d")}')
        if end_date:
            self.stdout.write(f'End date: {end_date.strftime("%Y-%m-%d")}')

        # Build CSV
        builder = PersonalizeItemCSVBuilder()
        stats = builder.build_csv(
            output_path=output_path,
            start_date=start_date,
            end_date=end_date,
        )

        # Display statistics
        self.stdout.write(self.style.SUCCESS("\nExport completed!"))
        self.stdout.write(f'Total items exported: {stats["total_items"]}')
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
