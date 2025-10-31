import argparse
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
        parser.add_argument(
            "--with-interactions",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Export items that have user interactions (default: True)",
        )
        parser.add_argument(
            "--with-posts",
            action="store_true",
            default=False,
            help=(
                "Include all ResearchHub posts regardless of interactions "
                "(can be filtered with --post-types)"
            ),
        )
        parser.add_argument(
            "--post-types",
            nargs="+",
            choices=["DISCUSSION", "QUESTION", "GRANT", "PREREGISTRATION"],
            help=(
                "Filter posts to specific types (only works with --with-posts). "
                "Choices: DISCUSSION, QUESTION, GRANT, PREREGISTRATION"
            ),
        )

    def handle(self, *args, **options):
        since_publish_date = self._parse_date(options.get("since_publish_date"))
        ids = options.get("ids")
        with_interactions = options.get("with_interactions", True)
        with_posts = options.get("with_posts", False)
        post_types = options.get("post_types")

        self.export_items(
            since_publish_date, ids, with_interactions, with_posts, post_types
        )

    def export_items(
        self,
        since_publish_date: Optional[datetime],
        ids: Optional[list] = None,
        with_interactions: bool = True,
        with_posts: bool = False,
        post_types: Optional[list] = None,
    ):
        """Export items from ResearchhubUnifiedDocument to CSV."""
        self.stdout.write("Exporting items...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"personalize_items_{timestamp}.csv"

        queryset = self._get_queryset(
            since_publish_date, ids, with_interactions, with_posts, post_types
        )

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No records found"))
            return

        self.stdout.write(f"Exporting {total} items to {filename}...")

        service = PersonalizeExportService(chunk_size=1000)

        def progress_callback(chunk_num: int, total_chunks: int, items_processed: int):
            """Display progress after each chunk."""
            self.stdout.write(
                f"Processing chunk {chunk_num}/{total_chunks} "
                f"({items_processed} items processed)",
                ending="\r",
            )

        exported, skipped = service.export_to_csv(
            queryset, filename, progress_callback=progress_callback, total_items=total
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nExport complete: {exported} exported"
                + (f", {skipped} skipped" if skipped else "")
                + f"\nFile: {filename}"
            )
        )

    def _build_base_queryset(self) -> QuerySet[ResearchhubUnifiedDocument]:
        """Build base queryset with all necessary relations and filters."""
        return (
            ResearchhubUnifiedDocument.objects.select_related(
                "paper",
            )
            .prefetch_related(
                "hubs",
                "related_bounties",
                "fundraises",
                "grants",
                "paper__authorships__author",
                "posts__authors",
            )
            .filter(
                is_removed=False,
                document_type__in=SUPPORTED_DOCUMENT_TYPES,
            )
        )

    def _get_interactions_filter(self) -> Q:
        """Get Q filter for documents with user interactions."""
        item_ids_with_interactions = set(
            UserInteractions.objects.values_list(
                "unified_document_id", flat=True
            ).distinct()
        )
        return Q(id__in=item_ids_with_interactions)

    def _get_posts_filter(self, post_types: Optional[list] = None) -> Q:
        """Get Q filter for all ResearchHub post documents.

        Args:
            post_types: Optional list of specific post types to filter.
                       If None, includes all post types.
        """
        # Default to all post types if not specified
        if not post_types:
            post_types = ["DISCUSSION", "QUESTION", "GRANT", "PREREGISTRATION"]
        return Q(document_type__in=post_types)

    def _get_date_filter(self, since_publish_date: datetime) -> Q:
        """Get Q filter for documents published/created since the given date."""
        papers_since_date = Q(
            document_type="PAPER",
            paper__paper_publish_date__gte=since_publish_date,
        )
        non_papers_since_date = Q(
            ~Q(document_type="PAPER"),
            created_date__gte=since_publish_date,
        )
        return papers_since_date | non_papers_since_date

    def _get_queryset(
        self,
        since_publish_date: Optional[datetime],
        ids: Optional[list] = None,
        with_interactions: bool = True,
        with_posts: bool = False,
        post_types: Optional[list] = None,
    ) -> QuerySet[ResearchhubUnifiedDocument]:
        base_queryset = self._build_base_queryset()

        if ids:
            return base_queryset.filter(id__in=ids).distinct().order_by("id")

        # Combine filters using Q objects (union of sets)
        combined_filter = Q()

        if with_interactions:
            combined_filter |= self._get_interactions_filter()

        if with_posts:
            combined_filter |= self._get_posts_filter(post_types)

        if since_publish_date:
            combined_filter |= self._get_date_filter(since_publish_date)

        if not combined_filter:
            return base_queryset.distinct().order_by("id")

        return base_queryset.filter(combined_filter).distinct().order_by("id")

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to datetime object."""
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Invalid date: {date_str}. Use YYYY-MM-DD")
