from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q, QuerySet

from analytics.constants.personalize_constants import SUPPORTED_DOCUMENT_TYPES
from analytics.models import UserInteractions
from analytics.services.personalize_export_service import PersonalizeExportService
from researchhub_document.models import ResearchhubUnifiedDocument


class Command(BaseCommand):
    help = "Export ResearchHub documents as Personalize items to CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since-publish-date",
            help="Include items published/created after this date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--ids",
            nargs="+",
            type=int,
            help="Specific unified document IDs to export (space-separated)",
        )

    def handle(self, *args, **options):
        since_publish_date = self._parse_date(options.get("since_publish_date"))
        ids = options.get("ids")

        self.export_items(since_publish_date, ids)

    def export_items(
        self,
        since_publish_date: Optional[datetime],
        ids: Optional[list] = None,
    ):
        """Export items from ResearchhubUnifiedDocument to CSV."""
        self.stdout.write("Exporting items...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"personalize_items_{timestamp}.csv"

        queryset = self._get_queryset(since_publish_date, ids)

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
        since_publish_date: Optional[datetime],
        ids: Optional[list] = None,
    ) -> QuerySet[ResearchhubUnifiedDocument]:
        base_queryset = (
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
        )

        if ids:
            return base_queryset.filter(id__in=ids).distinct().order_by("id")

        item_ids_with_interactions = set(
            UserInteractions.objects.values_list(
                "unified_document_id", flat=True
            ).distinct()
        )

        if since_publish_date:
            papers_since_date = Q(
                document_type="PAPER",
                paper__paper_publish_date__gte=since_publish_date,
            )
            non_papers_since_date = Q(
                ~Q(document_type="PAPER"),
                created_date__gte=since_publish_date,
            )
            items_since_date = papers_since_date | non_papers_since_date

            queryset = base_queryset.filter(
                Q(id__in=item_ids_with_interactions) | items_since_date
            )
        else:
            queryset = base_queryset.filter(id__in=item_ids_with_interactions)

        return queryset.distinct().order_by("id")

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Invalid date: {date_str}. Use YYYY-MM-DD")
