import csv
from typing import Iterator

from django.db.models import QuerySet

from analytics.constants.personalize_constants import CSV_HEADERS
from analytics.items.personalize_item_mapper import map_to_item
from analytics.utils.personalize_batch_queries import PersonalizeBatchQueries
from researchhub_document.models import ResearchhubUnifiedDocument


class PersonalizeExportService:
    """Service for exporting ResearchHub documents to Personalize format."""

    def __init__(self, chunk_size: int = 1000):
        self.chunk_size = chunk_size
        self.fetcher = PersonalizeBatchQueries()

    def export_items(
        self, queryset: QuerySet[ResearchhubUnifiedDocument]
    ) -> Iterator[dict]:
        """Export items from queryset as an iterator of CSV row dictionaries."""
        total = queryset.count()

        for chunk_start in range(0, total, self.chunk_size):
            chunk = list(queryset[chunk_start : chunk_start + self.chunk_size])

            for item_row in self._process_chunk(chunk):
                yield item_row

    def export_to_csv(
        self, queryset: QuerySet[ResearchhubUnifiedDocument], filename: str
    ) -> tuple[int, int]:
        """Export items directly to CSV file."""
        exported = 0
        skipped = 0

        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()

                for item_row in self.export_items(queryset):
                    try:
                        writer.writerow(item_row)
                        exported += 1
                    except Exception:
                        skipped += 1
        except PermissionError as e:
            raise PermissionError(f"Permission denied writing to {filename}: {e}")
        except OSError as e:
            raise OSError(f"Error writing to {filename}: {e}")

        return (exported, skipped)

    def _process_chunk(self, chunk: list[ResearchhubUnifiedDocument]) -> list[dict]:
        """Process a chunk of documents with batch fetching."""
        if not chunk:
            return []

        chunk_ids = [doc.id for doc in chunk]

        batch_data = self.fetcher.fetch_all(chunk_ids)
        bounty_data = batch_data["bounty"]
        proposal_data = batch_data["proposal"]
        rfp_data = batch_data["rfp"]
        review_count_data = batch_data["review_count"]

        items = []
        for unified_doc in chunk:
            try:
                item_row = map_to_item(
                    unified_doc,
                    bounty_data=bounty_data.get(unified_doc.id, {}),
                    proposal_data=proposal_data.get(unified_doc.id, {}),
                    rfp_data=rfp_data.get(unified_doc.id, {}),
                    review_count_data=review_count_data,
                )
                items.append(item_row)
            except Exception:
                continue

        return items
