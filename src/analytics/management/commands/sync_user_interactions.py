import csv
from datetime import datetime
from typing import List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import QuerySet

from analytics.constants.event_types import EVENT_WEIGHTS
from analytics.interactions.interaction_mapper import map_from_upvote
from analytics.models import UserInteractions
from discussion.models import Vote


class Command(BaseCommand):
    help = "Import/export user interactions for ML personalization"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            required=True,
            choices=["import", "export"],
        )
        parser.add_argument("--start-date", help="YYYY-MM-DD (UTC)")
        parser.add_argument("--end-date", help="YYYY-MM-DD (UTC)")
        parser.add_argument("--batch-size", type=int, default=1000)
        parser.add_argument(
            "--mark-synced",
            type=lambda x: x.lower() in ("true", "1", "yes"),
            default=True,
            help="Mark exported records as synced (default: True)",
        )

    def handle(self, *args, **options):
        mode = options["mode"]
        start_date = self._parse_date(options.get("start_date"))
        end_date = self._parse_date(options.get("end_date"))

        if start_date and end_date and start_date > end_date:
            raise CommandError("start-date must be before end-date")

        if mode == "import":
            self.handle_import(start_date, end_date, options["batch_size"])
        else:
            self.handle_export(start_date, end_date, options["mark_synced"])

    def handle_import(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        batch_size: int,
    ):
        """Import Interactions from source models into UserInteractions table."""

        self.stdout.write("Importing interactions...")

        queryset = self._get_upvote_queryset(start_date, end_date)
        total = queryset.count()

        if total == 0:
            self.stdout.write(self.style.WARNING("No records found"))
            return

        processed = 0
        created = 0
        skipped = 0
        batch = []

        for vote in queryset.iterator():
            try:
                batch.append(map_from_upvote(vote))
                processed += 1

                if len(batch) >= batch_size:
                    created += self._insert_batch(batch)
                    batch = []
                    self.stdout.write(
                        f"Progress: {processed}/{total} "
                        f"({created} created, {skipped} skipped)",
                        ending="\r",
                    )
            except ValueError as e:
                # Skip votes with missing required data
                skipped += 1
                if skipped <= 10:  # Only show first 10 warnings
                    self.stdout.write(self.style.WARNING(f"\nSkipping: {e}"))
                continue
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"\nUnexpected error: {e}"))
                continue

        if batch:
            created += self._insert_batch(batch)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nImport complete: {processed} processed, {created} created"
                + (f", {skipped} skipped" if skipped else "")
            )
        )

    def handle_export(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        mark_synced: bool,
    ):
        """Export Interactions from UserInteractions table"""
        self.stdout.write("Exporting interactions...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"user_interactions_{timestamp}.csv"

        queryset = UserInteractions.objects.select_related("user", "unified_document")
        if start_date:
            queryset = queryset.filter(event_timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(event_timestamp__lte=end_date)
        queryset = queryset.order_by("event_timestamp")

        total = queryset.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No records found"))
            return

        self.stdout.write(f"Exporting {total} records to {filename}...")

        exported = 0
        skipped = 0
        exported_ids = []

        with open(filename, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "USER_ID",
                    "SESSION_ID",
                    "ITEM_ID",
                    "TIMESTAMP",
                    "EVENT_TYPE",
                    "EVENT_VALUE",
                    "DEVICE",
                    "IMPRESSION",
                    "RECOMMENDATION_ID",
                ]
            )

            for interaction in queryset.iterator():
                # Skip if neither user_id nor session_id is present (one is required)
                if not interaction.user_id and not interaction.session_id:
                    skipped += 1
                    continue
                
                # Skip if unified_document_id is missing
                if not interaction.unified_document_id:
                    skipped += 1
                    continue

                event_weight = EVENT_WEIGHTS.get(interaction.event, 1.0)

                writer.writerow(
                    [
                        interaction.user_id or "",  # USER_ID (empty for anonymous)
                        interaction.session_id or "",  # SESSION_ID (empty for internal events)
                        interaction.unified_document_id,
                        int(interaction.event_timestamp.timestamp()),
                        interaction.event,
                        event_weight,
                        "",  # DEVICE - not yet tracked
                        "",  # IMPRESSION - not yet tracked
                        interaction.personalize_rec_id or "",  # RECOMMENDATION_ID
                    ]
                )
                exported += 1
                exported_ids.append(interaction.id)

                if exported % 1000 == 0:
                    self.stdout.write(f"Progress: {exported}/{total}", ending="\r")

        if mark_synced and exported_ids:
            UserInteractions.objects.filter(id__in=exported_ids).update(
                is_synced_with_personalize=True
            )
            sync_msg = f" (marked {len(exported_ids)} as synced)"
        else:
            sync_msg = ""

        self.stdout.write(
            self.style.SUCCESS(
                f"\nExport complete: {exported} exported"
                + (f", {skipped} skipped" if skipped else "")
                + sync_msg
                + f"\nFile: {filename}"
            )
        )

    @transaction.atomic
    def _insert_batch(self, batch: List[UserInteractions]) -> int:
        if not batch:
            return 0
        before = UserInteractions.objects.count()
        UserInteractions.objects.bulk_create(batch, ignore_conflicts=True)
        return UserInteractions.objects.count() - before

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            raise CommandError(f"Invalid date: {date_str}. Use YYYY-MM-DD")

    def _get_upvote_queryset(
        self, start_date: Optional[datetime], end_date: Optional[datetime]
    ) -> QuerySet:
        queryset = Vote.objects.select_related("created_by").filter(
            vote_type=Vote.UPVOTE
        )
        if start_date:
            queryset = queryset.filter(created_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_date__lte=end_date)
        return queryset
