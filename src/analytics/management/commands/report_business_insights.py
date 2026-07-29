"""Generate the database-backed business insights JSON report.

Run from the repository root:

    cd src
    python manage.py report_business_insights --period 7d --pretty
    python manage.py report_business_insights --period 7d \
        --output business_insights.json --pretty
    python manage.py report_business_insights --period 24h
    python manage.py report_business_insights --period 14d
    python manage.py report_business_insights --period 30d
    python manage.py report_business_insights \
        --start-date 2026-07-01 --end-date 2026-07-07 --pretty

Use ``python manage.py report_business_insights --help`` for all options.
The command always writes JSON to stdout. Pass ``--output`` to save a copy.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from analytics.services.business_insights_service import BusinessInsightsService
from analytics.services.insights.period import resolve_period


class BusinessInsightsJSONEncoder(DjangoJSONEncoder):
    """Serialize report decimals as user-friendly JSON numbers."""

    def default(self, value):
        if isinstance(value, Decimal):
            if value == value.to_integral_value():
                return int(value)
            return float(value)
        return super().default(value)


class Command(BaseCommand):
    help = "Output database-backed business insights as JSON"

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            choices=["24h", "7d", "14d", "30d"],
            default="7d",
            help="Reporting window ending now (default: 7d)",
        )
        parser.add_argument("--start-date", type=date.fromisoformat, help="YYYY-MM-DD")
        parser.add_argument("--end-date", type=date.fromisoformat, help="YYYY-MM-DD")
        parser.add_argument(
            "--pretty",
            action="store_true",
            help="Indent the JSON output",
        )
        parser.add_argument(
            "--output",
            type=Path,
            help="Write JSON to this file instead of stdout",
        )

    def handle(self, *args, **options):
        try:
            report_period = resolve_period(
                period=options["period"],
                start_date=options.get("start_date"),
                end_date=options.get("end_date"),
            )
        except ValueError as error:
            raise CommandError(str(error)) from error

        report = BusinessInsightsService(report_period).build()
        serialized_report = json.dumps(
            report,
            cls=BusinessInsightsJSONEncoder,
            indent=2 if options["pretty"] else None,
        )
        self.stdout.write(serialized_report)

        output_path = options.get("output")
        if output_path:
            output_path = output_path.expanduser().resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(f"{serialized_report}\n", encoding="utf-8")
            self.stderr.write(self.style.SUCCESS(f"Report written to {output_path}"))
