import csv
import time
from typing import Callable, Iterator, Optional

from django.db import connection, reset_queries
from django.db.models import QuerySet

from analytics.constants.personalize_constants import CSV_HEADERS
from analytics.items.personalize_item_mapper import PersonalizeItemMapper
from analytics.utils.personalize_related_data_fetcher import (
    PersonalizeRelatedDataFetcher,
)
from researchhub_document.models import ResearchhubUnifiedDocument


class PersonalizeExportService:
    """Service for exporting ResearchHub documents to Personalize format."""

    def __init__(self, chunk_size: int = 1000, debug: bool = False):
        self.chunk_size = chunk_size
        self.debug = debug
        self.fetcher = PersonalizeRelatedDataFetcher()
        self.mapper = PersonalizeItemMapper()
        self.chunk_timings = []  # Store timing details for debugging
        self.failed_ids = []  # Track IDs of items that failed to map

    def export_items(
        self,
        queryset: QuerySet[ResearchhubUnifiedDocument],
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        total_items: Optional[int] = None,
    ) -> Iterator[dict]:
        """Export items from queryset as an iterator of CSV row dicts.

        Args:
            queryset: The queryset to export
            progress_callback: Optional callback(chunk_num, total_chunks,
                items_processed) called after each chunk is processed
            total_items: Pre-calculated total count (avoids redundant query)
        """
        total = total_items if total_items is not None else queryset.count()
        total_chunks = (total + self.chunk_size - 1) // self.chunk_size
        items_processed = 0

        for chunk_num, chunk_start in enumerate(
            range(0, total, self.chunk_size), start=1
        ):
            chunk_timing = {"chunk_num": chunk_num}

            # Time chunk evaluation
            if self.debug:
                reset_queries()
                start = time.time()

            chunk = list(queryset[chunk_start : chunk_start + self.chunk_size])

            if self.debug:
                chunk_timing["eval_time"] = time.time() - start
                chunk_timing["eval_queries"] = len(connection.queries)
                chunk_timing["eval_queries_list"] = list(connection.queries)
                chunk_timing["chunk_size"] = len(chunk)

            # Time chunk processing
            if self.debug:
                reset_queries()
                start = time.time()

            processed_items = self._process_chunk(
                chunk, chunk_timing if self.debug else None
            )

            if self.debug:
                chunk_timing["process_time"] = time.time() - start
                chunk_timing["process_queries"] = len(connection.queries)
                self.chunk_timings.append(chunk_timing)

            for item_row in processed_items:
                yield item_row
                items_processed += 1

            if progress_callback:
                progress_callback(chunk_num, total_chunks, items_processed)

    def export_to_csv(
        self,
        queryset: QuerySet[ResearchhubUnifiedDocument],
        filename: str,
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
        total_items: Optional[int] = None,
    ) -> dict:
        """Export items directly to CSV file.

        Args:
            queryset: The queryset to export
            filename: Output CSV filename
            progress_callback: Optional callback(chunk_num, total_chunks,
                items_processed) called after each chunk is processed
            total_items: Pre-calculated total count (avoids redundant query)

        Returns:
            Dict with keys:
                - exported: Number of items successfully exported
                - skipped: Number of items that failed to write to CSV
                - failed_ids: List of unified document IDs that failed to map
        """
        exported = 0
        skipped = 0

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()

                for item_row in self.export_items(
                    queryset, progress_callback, total_items
                ):
                    try:
                        writer.writerow(item_row)
                        exported += 1
                    except Exception:
                        skipped += 1
        except PermissionError as e:
            raise PermissionError(f"Permission denied writing to {filename}: {e}")
        except OSError as e:
            raise OSError(f"Error writing to {filename}: {e}")

        return {
            "exported": exported,
            "skipped": skipped,
            "failed_ids": self.failed_ids,
        }

    def _process_chunk(
        self,
        chunk: list[ResearchhubUnifiedDocument],
        timing: Optional[dict] = None,
    ) -> list[dict]:
        """Process a chunk of documents with batch fetching."""
        if not chunk:
            return []

        chunk_ids = [doc.id for doc in chunk]

        # Time the fetch_all operation
        if timing is not None:
            reset_queries()
            start = time.time()

        batch_data = self.fetcher.fetch_all(chunk_ids)

        if timing is not None:
            timing["fetch_time"] = time.time() - start
            timing["fetch_queries"] = len(connection.queries)
            timing["fetch_queries_list"] = list(connection.queries)

        bounty_data = batch_data["bounty"]
        proposal_data = batch_data["proposal"]
        rfp_data = batch_data["rfp"]
        review_count_data = batch_data["review_count"]

        # Time the mapping operation
        if timing is not None:
            reset_queries()
            start = time.time()

        items = []
        for unified_doc in chunk:
            try:
                item_row = self.mapper.map_to_item(
                    unified_doc,
                    bounty_data=bounty_data.get(unified_doc.id, {}),
                    proposal_data=proposal_data.get(unified_doc.id, {}),
                    rfp_data=rfp_data.get(unified_doc.id, {}),
                    review_count_data=review_count_data,
                )
                items.append(item_row)
            except Exception:
                self.failed_ids.append(unified_doc.id)
                continue

        if timing is not None:
            timing["map_time"] = time.time() - start
            timing["map_queries"] = len(connection.queries)
            timing["map_queries_list"] = list(connection.queries)
            timing["items_mapped"] = len(items)

        return items
