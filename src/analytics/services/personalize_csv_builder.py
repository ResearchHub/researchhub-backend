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
            elif mapper_class_name == "RfpMapper":
                from analytics.services.personalize_mappers import rfp_mapper

                mappers.append(rfp_mapper.RfpMapper())
            elif mapper_class_name == "ProposalMapper":
                from analytics.services.personalize_mappers import proposal_mapper

                mappers.append(proposal_mapper.ProposalMapper())
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

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(INTERACTION_CSV_HEADERS)

            for mapper in self.mappers:
                event_stats = self._process_mapper(
                    mapper, writer, start_date, end_date, progress_callback
                )

                stats["total_records"] += event_stats["records_processed"]
                interactions_count = event_stats["interactions_exported"]
                stats["interactions_exported"] += interactions_count
                stats["records_skipped"] += event_stats["records_skipped"]
                stats["by_event_type"][mapper.event_type_name] = event_stats

        return stats

    def _process_mapper(self, mapper, writer, start_date, end_date, progress_callback):
        """Process a single mapper's records."""
        stats = {
            "records_processed": 0,
            "interactions_exported": 0,
            "records_skipped": 0,
        }

        queryset = mapper.get_queryset(start_date, end_date)
        stats["records_processed"] = queryset.count()

        for record in queryset.iterator():
            interactions = mapper.map_to_interactions(record)

            if not interactions:
                stats["records_skipped"] += 1
                continue

            for interaction in interactions:
                row = format_interaction_csv_row(interaction)
                writer.writerow(row)
                stats["interactions_exported"] += 1

            if progress_callback:
                progress_callback(
                    stats["records_processed"],
                    stats["interactions_exported"],
                    stats["records_skipped"],
                )

        return stats
