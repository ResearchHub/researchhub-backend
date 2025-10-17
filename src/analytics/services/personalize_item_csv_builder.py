"""
CSV builder for AWS Personalize item data export.

Orchestrates the item export process by using ItemMapper to convert
unified documents to CSV rows and writing them to a file.
"""

import csv
import os
from typing import Dict, Optional

from analytics.services.personalize_item_constants import CSV_HEADERS
from analytics.services.personalize_item_mapper import ItemMapper


class PersonalizeItemCSVBuilder:
    """Builds CSV file of items for AWS Personalize."""

    def __init__(self):
        """Initialize the CSV builder with an ItemMapper."""
        self.mapper = ItemMapper()

    def build_csv(
        self,
        output_path: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        item_ids: Optional[set] = None,
        since_date: Optional[str] = None,
    ) -> Dict[str, int]:
        """
        Build CSV file of items for AWS Personalize.

        Args:
            output_path: Path where the CSV file will be written
            start_date: Optional filter for documents created after this date
            end_date: Optional filter for documents created before this date
            item_ids: Optional set of item IDs to filter by (from interactions)
            since_date: Optional date to include all papers created on/after this date

        Returns:
            Dictionary with statistics:
            - total_items: Total number of items exported
            - papers: Number of paper items
            - posts: Number of post items
            - filtered_by_interactions: Boolean indicating if filtering was applied
        """
        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Get queryset
        queryset = self.mapper.get_queryset(start_date, end_date, item_ids, since_date)
        total_count = queryset.count()

        # Initialize statistics
        stats = {
            "total_items": 0,
            "papers": 0,
            "posts": 0,
            "by_type": {},
            "filtered_by_interactions": item_ids is not None,
        }

        # Write CSV
        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=CSV_HEADERS)
            writer.writeheader()

            # Process documents in batches
            batch_size = 1000
            for i in range(0, total_count, batch_size):
                batch = queryset[i : i + batch_size]

                for unified_doc in batch:
                    try:
                        row = self.mapper.map_to_item_row(unified_doc)

                        # Convert None values to empty strings for CSV
                        csv_row = {k: ("" if v is None else v) for k, v in row.items()}

                        writer.writerow(csv_row)

                        # Update statistics
                        stats["total_items"] += 1

                        doc_type = unified_doc.document_type
                        if doc_type == "PAPER":
                            stats["papers"] += 1
                        else:
                            stats["posts"] += 1

                        # Count by document type
                        if doc_type not in stats["by_type"]:
                            stats["by_type"][doc_type] = 0
                        stats["by_type"][doc_type] += 1

                    except Exception as e:
                        # Log error but continue processing
                        print(f"Error processing document {unified_doc.id}: {e}")
                        continue

        return stats
