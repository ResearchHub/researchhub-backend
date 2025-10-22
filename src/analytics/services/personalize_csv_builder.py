"""
Generic CSV builder for Personalize exports.

This builder orchestrates multiple event type mappers to create
a unified CSV export for AWS Personalize.
"""

import csv
from typing import List, Optional

from analytics.services.personalize_constants import (
    EVENT_TYPE_CONFIGS,
    INTERACTION_CSV_HEADERS,
)
from analytics.services.personalize_utils import format_interaction_csv_row


class PersonalizeCSVBuilder:
    """Builds CSV files for AWS Personalize from multiple event types."""

    def __init__(self, event_types: Optional[List[str]] = None):
        """
        Initialize the CSV builder.

        Args:
            event_types: List of event type names to include.
                        If None, includes all enabled event types.
        """
        self.event_types = event_types or self._get_enabled_event_types()
        self.mappers = self._initialize_mappers()

    def _get_enabled_event_types(self) -> List[str]:
        """Get list of enabled event types from config."""
        return [
            event_type
            for event_type, config in EVENT_TYPE_CONFIGS.items()
            if config.get("enabled", False)
        ]

    def _initialize_mappers(self):
        """Initialize mapper instances for each event type."""
        mappers = []
        for event_type in self.event_types:
            config = EVENT_TYPE_CONFIGS.get(event_type)
            if not config:
                continue

            mapper_class_name = config.get("mapper_class")
            if mapper_class_name == "BountySolutionMapper":
                from analytics.services.personalize_mappers import (
                    bounty_solution_mapper,
                )

                mappers.append(bounty_solution_mapper.BountySolutionMapper())
            elif mapper_class_name == "BountyMapper":
                from analytics.services.personalize_mappers import bounty_mapper

                mappers.append(bounty_mapper.BountyMapper())
            elif mapper_class_name == "BountyContributionMapper":
                from analytics.services.personalize_mappers import (
                    bounty_contribution_mapper,
                )

                mappers.append(bounty_contribution_mapper.BountyContributionMapper())
            elif mapper_class_name == "RfpMapper":
                from analytics.services.personalize_mappers import rfp_mapper

                mappers.append(rfp_mapper.RfpMapper())
            elif mapper_class_name == "RfpApplicationMapper":
                from analytics.services.personalize_mappers import (
                    rfp_application_mapper,
                )

                mappers.append(rfp_application_mapper.RfpApplicationMapper())
            elif mapper_class_name == "ProposalMapper":
                from analytics.services.personalize_mappers import proposal_mapper

                mappers.append(proposal_mapper.ProposalMapper())
            elif mapper_class_name == "ProposalFundingMapper":
                from analytics.services.personalize_mappers import (
                    proposal_funding_mapper,
                )

                mappers.append(proposal_funding_mapper.ProposalFundingMapper())
            elif mapper_class_name == "PeerReviewMapper":
                from analytics.services.personalize_mappers import peer_review_mapper

                mappers.append(peer_review_mapper.PeerReviewMapper())
            elif mapper_class_name == "CommentMapper":
                from analytics.services.personalize_mappers import comment_mapper

                mappers.append(comment_mapper.CommentMapper())
            elif mapper_class_name == "UpvoteMapper":
                from analytics.services.personalize_mappers import upvote_mapper

                mappers.append(upvote_mapper.UpvoteMapper())
            elif mapper_class_name == "PreprintMapper":
                from analytics.services.personalize_mappers import preprint_mapper

                mappers.append(preprint_mapper.PreprintMapper())
            # Future mappers can be added here with elif statements
            # elif mapper_class_name == "PaperViewMapper":
            #     from analytics.services.personalize_mappers.paper_view_mapper import (
            #         PaperViewMapper,
            #     )
            #     mappers.append(PaperViewMapper())

        return mappers

    def export_to_csv(
        self,
        output_path: str,
        start_date=None,
        end_date=None,
        progress_callback=None,
    ):
        """
        Export interactions to CSV file.

        Args:
            output_path: Path to output CSV file
            start_date: Optional start date filter
            end_date: Optional end date filter
            progress_callback: Optional callback function for progress updates
                Called with (records_processed, interactions_exported, skipped)

        Returns:
            dict with statistics about the export
        """
        stats = {
            "total_records": 0,
            "interactions_exported": 0,
            "records_skipped": 0,
            "by_event_type": {},
        }

        # Track unique item IDs for cache file
        seen_item_ids = set()
        all_skipped_records = []

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(INTERACTION_CSV_HEADERS)

            for mapper in self.mappers:
                event_stats, skipped_records = self._process_mapper(
                    mapper,
                    writer,
                    start_date,
                    end_date,
                    progress_callback,
                    seen_item_ids,
                )

                stats["total_records"] += event_stats["records_processed"]
                interactions_count = event_stats["interactions_exported"]
                stats["interactions_exported"] += interactions_count
                stats["records_skipped"] += event_stats["records_skipped"]
                stats["by_event_type"][mapper.event_type_name] = event_stats
                all_skipped_records.extend(skipped_records)

        # Write item IDs cache file
        self._write_item_ids_cache(output_path, seen_item_ids)
        stats["unique_items"] = len(seen_item_ids)

        # Write skipped records log if there are any
        if all_skipped_records:
            self._write_skipped_records_log(output_path, all_skipped_records)

        return stats

    def _process_mapper(
        self, mapper, writer, start_date, end_date, progress_callback, seen_item_ids
    ):
        """Process a single mapper's records."""
        stats = {
            "records_processed": 0,
            "interactions_exported": 0,
            "records_skipped": 0,
        }

        # Track skipped records for detailed logging
        skipped_records = []

        queryset = mapper.get_queryset(start_date, end_date)
        stats["records_processed"] = queryset.count()

        for record in queryset.iterator():
            interactions = mapper.map_to_interactions(record)

            if not interactions:
                stats["records_skipped"] += 1

                # Log details about the skipped record
                record_info = {
                    "mapper": mapper.event_type_name,
                    "record_id": getattr(record, "id", "unknown"),
                    "record_type": type(record).__name__,
                    "record_str": str(record)[:200],  # First 200 chars
                }

                # Try to get more specific info based on record type
                if hasattr(record, "unified_document"):
                    record_info["unified_doc_id"] = getattr(
                        record.unified_document, "id", "None"
                    )
                    record_info["unified_doc_type"] = getattr(
                        record.unified_document, "document_type", "None"
                    )
                elif hasattr(record, "content_object"):
                    record_info["content_object_id"] = getattr(
                        record.content_object, "id", "None"
                    )
                    record_info["content_object_type"] = type(
                        record.content_object
                    ).__name__

                skipped_records.append(record_info)
                continue

            for interaction in interactions:
                row = format_interaction_csv_row(interaction)
                writer.writerow(row)
                stats["interactions_exported"] += 1

                # Track item ID for cache
                if interaction.get("ITEM_ID"):
                    seen_item_ids.add(str(interaction["ITEM_ID"]))

            if progress_callback:
                progress_callback(
                    stats["records_processed"],
                    stats["interactions_exported"],
                    stats["records_skipped"],
                )

        return stats, skipped_records

    def _write_item_ids_cache(self, output_path: str, item_ids: set):
        """
        Write unique item IDs to cache file.

        Args:
            output_path: Path to the interactions CSV file
            item_ids: Set of unique item IDs to write
        """
        cache_path = output_path.replace(".csv", ".item_ids.cache")
        with open(cache_path, "w", encoding="utf-8") as f:
            for item_id in sorted(item_ids, key=lambda x: int(x)):
                f.write(f"{item_id}\n")

    def _write_skipped_records_log(self, output_path: str, skipped_records: list):
        """
        Write skipped records to a log file for investigation.

        Args:
            output_path: Path to the interactions CSV file
            skipped_records: List of skipped record information
        """
        from datetime import datetime

        log_path = output_path.replace(".csv", ".skipped_records.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"Skipped Records Log - {datetime.now()}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Total skipped records: {len(skipped_records)}\n\n")

            # Group by mapper for better organization
            by_mapper = {}
            for record_info in skipped_records:
                mapper = record_info["mapper"]
                if mapper not in by_mapper:
                    by_mapper[mapper] = []
                by_mapper[mapper].append(record_info)

            for mapper, records in by_mapper.items():
                f.write(f"=== {mapper} ({len(records)} records) ===\n")
                for i, record_info in enumerate(records, 1):
                    f.write(f"\nRecord {i}:\n")
                    f.write(f"  ID: {record_info['record_id']}\n")
                    f.write(f"  Type: {record_info['record_type']}\n")
                    f.write(f"  String: {record_info['record_str']}\n")

                    if "unified_doc_id" in record_info:
                        f.write(f"  Unified Doc ID: {record_info['unified_doc_id']}\n")
                        f.write(
                            f"  Unified Doc Type: {record_info['unified_doc_type']}\n"
                        )
                    elif "content_object_id" in record_info:
                        f.write(
                            f"  Content Object ID: {record_info['content_object_id']}\n"
                        )
                        f.write(
                            f"  Content Object Type: "
                            f"{record_info['content_object_type']}\n"
                        )

                    f.write("-" * 40 + "\n")
                f.write("\n")
