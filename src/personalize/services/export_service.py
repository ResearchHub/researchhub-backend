import csv
import time
from typing import Callable, Iterator, Optional

from django.db import connection, reset_queries
from django.db.models import QuerySet

from personalize.config.constants import CSV_HEADERS
from personalize.services.item_mapper import ItemMapper
from personalize.utils.related_data_fetcher import RelatedDataFetcher
from researchhub_document.models import ResearchhubUnifiedDocument


class ExportService:
    """Service for exporting ResearchHub documents to Personalize format."""

    def __init__(
        self, chunk_size: int = 1000, debug: bool = False, since_publish_date=None
    ):
        self.chunk_size = chunk_size
        self.debug = debug
        self.since_publish_date = since_publish_date
        self.fetcher = RelatedDataFetcher()
        self.mapper = ItemMapper()
        self.chunk_timings = []  # Store timing details for debugging
        self.failed_ids = []  # Track IDs of items that failed to map
        self.failed_reasons = {}  # Track failure reasons for debugging
        self.filtered_by_date_ids = []  # Track IDs filtered by publish date

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

        # Use ID-based pagination for better performance
        last_id = 0
        chunk_num = 0

        while True:
            chunk_num += 1
            chunk_timing = {"chunk_num": chunk_num}

            # Time chunk evaluation
            if self.debug:
                reset_queries()
                start = time.time()

            # Filter using ID-based pagination instead of offset
            chunk = list(
                queryset.filter(id__gt=last_id).order_by("id")[: self.chunk_size]
            )

            # Break if no more items
            if not chunk:
                break

            # Batch load papers for this chunk
            paper_doc_ids = [doc.id for doc in chunk if doc.document_type == "PAPER"]
            if paper_doc_ids:
                from paper.models import Paper

                papers = Paper.objects.filter(
                    unified_document_id__in=paper_doc_ids
                ).in_bulk(field_name="unified_document_id")
                # Attach papers to their unified documents
                for doc in chunk:
                    if doc.document_type == "PAPER" and doc.id in papers:
                        doc.paper = papers[doc.id]

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

            # Update last_id to the last item's ID in this chunk
            last_id = chunk[-1].id

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
                - csv_errors: Number of items that failed to write to CSV
                - failed_ids: List of unified document IDs that failed to map
                - filtered_by_date_ids: List of paper IDs filtered by publish date
        """
        exported = 0
        csv_errors = 0

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
                        csv_errors += 1
        except PermissionError as e:
            raise PermissionError(f"Permission denied writing to {filename}: {e}")
        except OSError as e:
            raise OSError(f"Error writing to {filename}: {e}")

        return {
            "exported": exported,
            "csv_errors": csv_errors,
            "failed_ids": self.failed_ids,
            "filtered_by_date_ids": self.filtered_by_date_ids,
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
            # Pre-filter papers by publish date
            if unified_doc.document_type == "PAPER" and self.since_publish_date:
                if hasattr(unified_doc, "paper") and unified_doc.paper:
                    paper_date = unified_doc.paper.paper_publish_date
                    if paper_date and paper_date < self.since_publish_date:
                        self.filtered_by_date_ids.append(unified_doc.id)
                        continue  # Skip - filtered by publish date

            try:
                item_row = self.mapper.map_to_csv_item(
                    unified_doc,
                    bounty_data=bounty_data.get(unified_doc.id, {}),
                    proposal_data=proposal_data.get(unified_doc.id, {}),
                    rfp_data=rfp_data.get(unified_doc.id, {}),
                    review_count_data=review_count_data,
                )
                items.append(item_row)
            except Exception as e:
                self.failed_ids.append(unified_doc.id)
                if self.debug:
                    self.failed_reasons[unified_doc.id] = (
                        f"{unified_doc.document_type}: {str(e)}"
                    )
                continue

        if timing is not None:
            timing["map_time"] = time.time() - start
            timing["map_queries"] = len(connection.queries)
            timing["map_queries_list"] = list(connection.queries)
            timing["items_mapped"] = len(items)

        return items
