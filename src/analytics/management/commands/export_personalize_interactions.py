"""
Django management command to export interactions to CSV for AWS Personalize.

Export bounty solution interactions to CSV for AWS Personalize.

Usage:
    python manage.py export_personalize_interactions
    python manage.py export_personalize_interactions --start-date 2024-01-01
    python manage.py export_personalize_interactions --event-types bounty_solution
"""

import os
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from analytics.services.personalize_csv_builder import PersonalizeCSVBuilder


class Command(BaseCommand):
    help = "Export interactions to CSV for AWS Personalize"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date for filtering (YYYY-MM-DD format)",
            default=None,
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date for filtering (YYYY-MM-DD format)",
            default=None,
        )
        parser.add_argument(
            "--output-path",
            type=str,
            help="Output CSV file path",
            default=".tmp/personalize_interactions.csv",
        )
        parser.add_argument(
            "--event-types",
            type=str,
            nargs="+",
            help="Event types to export (default: all enabled)",
            default=None,
        )

    def handle(self, *args, **options):
        start_date = options["start_date"]
        end_date = options["end_date"]
        output_path = options["output_path"]
        event_types = options["event_types"]

        # Parse dates
        start_datetime = self._parse_date(start_date, "start")
        end_datetime = self._parse_date(end_date, "end")

        if (start_date and not start_datetime) or (end_date and not end_datetime):
            return

        # Ensure output directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Build CSV
        self.stdout.write("Initializing CSV builder...")
        builder = PersonalizeCSVBuilder(event_types=event_types)

        event_type_names = [m.event_type_name for m in builder.mappers]
        self.stdout.write(f"Event types: {', '.join(event_type_names)}")

        stats = builder.export_to_csv(
            output_path,
            start_date=start_datetime,
            end_date=end_datetime,
        )

        # Report statistics
        self._print_stats(stats, output_path)

    def _parse_date(self, date_str, date_type):
        """Parse and validate date string."""
        if not date_str:
            return None

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if date_type == "end":
                dt = dt.replace(hour=23, minute=59, second=59)
            self.stdout.write(f"Filtering {date_type}: {dt.date()}")
            return dt
        except ValueError:
            self.stderr.write(
                self.style.ERROR(
                    f"Invalid {date_type} date: {date_str}. Use YYYY-MM-DD"
                )
            )
            return None

    def _print_stats(self, stats, output_path):
        """Print export statistics."""
        self.stdout.write(self.style.SUCCESS("\n=== Export Complete ==="))
        self.stdout.write(f"Total records processed: {stats['total_records']}")
        self.stdout.write(
            f"Records skipped (no unified doc): {stats['records_skipped']}"
        )
        self.stdout.write(f"Interactions exported: {stats['interactions_exported']}")

        self.stdout.write("\nBy event type:")
        for event_type, event_stats in stats["by_event_type"].items():
            self.stdout.write(
                f"  {event_type}: {event_stats['interactions_exported']} "
                f"interactions ({event_stats['records_processed']} records)"
            )

        self.stdout.write(f"\nOutput file: {os.path.abspath(output_path)}")
        success_msg = (
            f"\nSuccessfully exported {stats['interactions_exported']} " "interactions"
        )
        self.stdout.write(self.style.SUCCESS(success_msg))
