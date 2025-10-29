from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db.models import QuerySet

from analytics.constants.personalize_constants import SUPPORTED_DOCUMENT_TYPES
from analytics.services.personalize_export_service import PersonalizeExportService
from researchhub_document.models import ResearchhubUnifiedDocument


class Command(BaseCommand):
    help = "Export ResearchHub documents as Personalize items to CSV"

    def add_arguments(self, parser):
        parser.add_argument("--start-date", help="YYYY-MM-DD (UTC)")
        parser.add_argument("--end-date", help="YYYY-MM-DD (UTC)")
        parser.add_argument(
            "--ids",
            nargs="+",
            type=int,
            help="Specific unified document IDs to export (space-separated)",
        )

    def handle(self, *args, **options):
        start_date = self._parse_date(options.get("start_date"))
        end_date = self._parse_date(options.get("end_date"))
        ids = options.get("ids")

        if start_date and end_date and start_date > end_date:
            raise CommandError("start-date must be before end-date")

        self.export_items(start_date, end_date, ids)

    def export_items(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        ids: Optional[list] = None,
    ):
        """Export items from ResearchhubUnifiedDocument to CSV."""
        self.stdout.write("Exporting items...")

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"personalize_items_{timestamp}.csv"

        # Build queryset with optimizations
        queryset = self._get_queryset(start_date, end_date, ids)

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No records found"))
            return

        self.stdout.write(f"Exporting {total} items to {filename}...")

        service = PersonalizeExportService(chunk_size=1000)
        exported, skipped = service.export_to_csv(queryset, filename)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nExport complete: {exported} exported"
                + (f", {skipped} skipped" if skipped else "")
                + f"\nFile: {filename}"
            )
        )

    def _get_queryset(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        ids: Optional[list] = None,
    ) -> QuerySet[ResearchhubUnifiedDocument]:
        queryset = (
            ResearchhubUnifiedDocument.objects.select_related(
                "document_filter",
                "paper",
            )
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "grants__contacts__author_profile",
                "paper__authorships__author",
                "posts__authors",
            )
            .filter(
                is_removed=False,
                document_type__in=SUPPORTED_DOCUMENT_TYPES,
            )
            .exclude(document_filter__is_excluded_in_feed=True)
        )

        if ids:
            queryset = queryset.filter(id__in=ids)
        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)

        return queryset.distinct().order_by("id")

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Invalid date: {date_str}. Use YYYY-MM-DD")
