import argparse
import time
from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, reset_queries
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
        parser.add_argument(
            "--debug",
            action="store_true",
            default=False,
            help="Enable detailed performance debugging output",
        )

    def handle(self, *args, **options):
        since_publish_date = self._parse_date(options.get("since_publish_date"))
        ids = options.get("ids")
        with_interactions = options.get("with_interactions", True)
        with_posts = options.get("with_posts", False)
        post_types = options.get("post_types")
        self.debug_mode = options.get("debug", False)

        if self.debug_mode:
            self.stdout.write(self.style.WARNING("\n=== DEBUG MODE ENABLED ===\n"))

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

        # Track performance metrics
        perf_metrics = {
            "queryset_build_time": 0,
            "count_time": 0,
            "export_time": 0,
            "chunks": [],
        }

        # Build queryset with timing
        if self.debug_mode:
            reset_queries()
            start = time.time()

        queryset = self._get_queryset(
            since_publish_date, ids, with_interactions, with_posts, post_types
        )

        if self.debug_mode:
            perf_metrics["queryset_build_time"] = time.time() - start
            perf_metrics["queryset_build_queries"] = len(connection.queries)
            self._debug_log(
                f"Queryset built in {perf_metrics['queryset_build_time']:.2f}s"
            )
            self._debug_log(
                f"Queries during build: {perf_metrics['queryset_build_queries']}"
            )

        # Count with timing
        if self.debug_mode:
            reset_queries()
            start = time.time()

        total = queryset.count()

        if self.debug_mode:
            perf_metrics["count_time"] = time.time() - start
            perf_metrics["count_queries"] = len(connection.queries)
            self._debug_log(f"Count executed in {perf_metrics['count_time']:.2f}s")
            self._debug_log(f"Queries during count: {perf_metrics['count_queries']}")

        if total == 0:
            self.stdout.write(self.style.WARNING("No records found"))
            return

        self.stdout.write(f"Exporting {total} items to {filename}...")

        service = PersonalizeExportService(chunk_size=1000, debug=self.debug_mode)

        # Track chunk-level metrics
        chunk_metrics = []
        last_chunk_time = time.time()

        def progress_callback(chunk_num: int, total_chunks: int, items_processed: int):
            """Display progress after each chunk."""
            nonlocal last_chunk_time

            if self.debug_mode:
                chunk_duration = time.time() - last_chunk_time
                query_count = len(connection.queries)
                chunk_metrics.append(
                    {
                        "chunk": chunk_num,
                        "duration": chunk_duration,
                        "queries": query_count,
                        "items": items_processed,
                    }
                )
                self._debug_log(
                    f"\nChunk {chunk_num}/{total_chunks}: {chunk_duration:.2f}s, "
                    f"{query_count} queries, {items_processed} items"
                )
                reset_queries()
                last_chunk_time = time.time()
            else:
                self.stdout.write(
                    f"Processing chunk {chunk_num}/{total_chunks} "
                    f"({items_processed} items processed)",
                    ending="\r",
                )

        if self.debug_mode:
            reset_queries()
            start = time.time()

        exported, skipped = service.export_to_csv(
            queryset, filename, progress_callback=progress_callback, total_items=total
        )

        if self.debug_mode:
            perf_metrics["export_time"] = time.time() - start
            perf_metrics["chunks"] = chunk_metrics

        self.stdout.write(
            self.style.SUCCESS(
                f"\nExport complete: {exported} exported"
                + (f", {skipped} skipped" if skipped else "")
                + f"\nFile: {filename}"
            )
        )

        # Print debug summary
        if self.debug_mode:
            self._print_debug_summary(perf_metrics, total, service)

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

    def _debug_log(self, message: str):
        """Output debug message."""
        self.stdout.write(self.style.WARNING(f"[DEBUG] {message}"))

    def _print_debug_summary(self, perf_metrics: dict, total_items: int, service):
        """Print comprehensive debug summary."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.WARNING("DEBUG PERFORMANCE SUMMARY"))
        self.stdout.write("=" * 80)

        # Overall timing
        self.stdout.write("\n📊 OVERALL TIMING:")
        self.stdout.write(
            f"  • Queryset build:  {perf_metrics['queryset_build_time']:.2f}s "
            f"({perf_metrics.get('queryset_build_queries', 0)} queries)"
        )
        self.stdout.write(
            f"  • Count operation: {perf_metrics['count_time']:.2f}s "
            f"({perf_metrics.get('count_queries', 0)} queries)"
        )
        self.stdout.write(f"  • Export operation: {perf_metrics['export_time']:.2f}s")
        total_time = (
            perf_metrics["queryset_build_time"]
            + perf_metrics["count_time"]
            + perf_metrics["export_time"]
        )
        self.stdout.write(f"  • TOTAL TIME:      {total_time:.2f}s")

        # Detailed chunk timing breakdown from service
        chunk_timings = service.chunk_timings
        if chunk_timings:
            self.stdout.write("\n📦 DETAILED CHUNK BREAKDOWN:")
            self.stdout.write(f"  • Total chunks: {len(chunk_timings)}")

            # Calculate averages for each operation
            eval_times = [c.get("eval_time", 0) for c in chunk_timings]
            fetch_times = [c.get("fetch_time", 0) for c in chunk_timings]
            map_times = [c.get("map_time", 0) for c in chunk_timings]

            eval_queries = [c.get("eval_queries", 0) for c in chunk_timings]
            fetch_queries = [c.get("fetch_queries", 0) for c in chunk_timings]
            map_queries = [c.get("map_queries", 0) for c in chunk_timings]

            self.stdout.write("\n  ⏱️  AVERAGE TIME BREAKDOWN PER CHUNK:")
            self.stdout.write(
                f"     • Queryset eval:  {sum(eval_times)/len(eval_times):.2f}s "
                f"(avg {sum(eval_queries)/len(eval_queries):.0f} queries)"
            )
            self.stdout.write(
                f"     • Fetch data:     {sum(fetch_times)/len(fetch_times):.2f}s "
                f"(avg {sum(fetch_queries)/len(fetch_queries):.0f} queries)"
            )
            self.stdout.write(
                f"     • Map to items:   {sum(map_times)/len(map_times):.2f}s "
                f"(avg {sum(map_queries)/len(map_queries):.0f} queries)"
            )
            total_avg = (
                sum(eval_times) / len(eval_times)
                + sum(fetch_times) / len(fetch_times)
                + sum(map_times) / len(map_times)
            )
            self.stdout.write(f"     • TOTAL AVG:      {total_avg:.2f}s")

            # Show slowest chunks with breakdown
            total_chunk_times = [
                c.get("eval_time", 0) + c.get("fetch_time", 0) + c.get("map_time", 0)
                for c in chunk_timings
            ]
            slowest_indices = sorted(
                range(len(total_chunk_times)),
                key=lambda i: total_chunk_times[i],
                reverse=True,
            )[:5]

            self.stdout.write("\n  🐌 SLOWEST CHUNKS (with breakdown):")
            for idx in slowest_indices:
                chunk = chunk_timings[idx]
                self.stdout.write(
                    f"     Chunk {chunk['chunk_num']}: {total_chunk_times[idx]:.2f}s total"
                )
                self.stdout.write(
                    f"       - Eval: {chunk.get('eval_time', 0):.2f}s ({chunk.get('eval_queries', 0)} queries)"
                )
                self.stdout.write(
                    f"       - Fetch: {chunk.get('fetch_time', 0):.2f}s ({chunk.get('fetch_queries', 0)} queries)"
                )
                self.stdout.write(
                    f"       - Map: {chunk.get('map_time', 0):.2f}s ({chunk.get('map_queries', 0)} queries)"
                )
                self.stdout.write(
                    f"       - Items: {chunk.get('chunk_size', 0)} in chunk, {chunk.get('items_mapped', 0)} mapped"
                )

            # Show most query-heavy operation
            self.stdout.write("\n  🔍 QUERY ANALYSIS:")
            total_eval_q = sum(eval_queries)
            total_fetch_q = sum(fetch_queries)
            total_map_q = sum(map_queries)
            total_q = total_eval_q + total_fetch_q + total_map_q

            self.stdout.write(f"     • Total queries: {total_q}")
            self.stdout.write(
                f"       - Queryset eval: {total_eval_q} ({total_eval_q/total_q*100:.1f}%)"
            )
            self.stdout.write(
                f"       - Fetch data:    {total_fetch_q} ({total_fetch_q/total_q*100:.1f}%)"
            )
            self.stdout.write(
                f"       - Map items:     {total_map_q} ({total_map_q/total_q*100:.1f}%)"
            )

        # Performance insights
        self.stdout.write("\n💡 INSIGHTS:")
        if chunk_timings:
            avg_fetch_time = sum(fetch_times) / len(fetch_times)
            avg_eval_time = sum(eval_times) / len(eval_times)
            avg_map_time = sum(map_times) / len(map_times)

            # Identify bottleneck
            if avg_fetch_time > avg_eval_time and avg_fetch_time > avg_map_time:
                self.stdout.write(
                    f"  🎯 BOTTLENECK: Data fetching ({avg_fetch_time:.2f}s avg)"
                )
                avg_fetch_q = sum(fetch_queries) / len(fetch_queries)
                if avg_fetch_q > 10:
                    self.stdout.write(
                        f"     - High query count in fetch ({avg_fetch_q:.0f} avg) - consider optimizing PersonalizeRelatedDataFetcher"
                    )
            elif avg_eval_time > avg_fetch_time and avg_eval_time > avg_map_time:
                self.stdout.write(
                    f"  🎯 BOTTLENECK: Queryset evaluation ({avg_eval_time:.2f}s avg)"
                )
                avg_eval_q = sum(eval_queries) / len(eval_queries)
                if avg_eval_q > 100:
                    self.stdout.write(
                        f"     - High query count ({avg_eval_q:.0f} avg) - prefetch_related may not be working"
                    )
            elif avg_map_time > avg_fetch_time and avg_map_time > avg_eval_time:
                self.stdout.write(
                    f"  🎯 BOTTLENECK: Item mapping ({avg_map_time:.2f}s avg)"
                )
                avg_map_q = sum(map_queries) / len(map_queries)
                if avg_map_q > 10:
                    self.stdout.write(
                        f"     - Mapping triggering queries ({avg_map_q:.0f} avg) - possible N+1 in mapper"
                    )

            # General warnings
            total_avg_time = avg_eval_time + avg_fetch_time + avg_map_time
            if total_avg_time > 30:
                self.stdout.write(
                    "  ⚠️  Chunks taking >30s on average - SEVERE performance issue"
                )
            elif total_avg_time > 10:
                self.stdout.write(
                    "  ⚠️  Chunks taking >10s on average - significant performance issue"
                )

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("Copy the above output to share for debugging")
        self.stdout.write("=" * 80 + "\n")
