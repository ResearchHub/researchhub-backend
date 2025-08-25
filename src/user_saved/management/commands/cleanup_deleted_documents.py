"""
Management command to clean up user saved entries for deleted documents
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from user_saved.models import UserSavedEntry


class Command(BaseCommand):
    help = "Clean up user saved entries for deleted documents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making changes",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of entries to process in each batch",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        self.stdout.write(
            self.style.SUCCESS(
                f"Starting cleanup of deleted document entries "
                f"(dry_run={dry_run}, batch_size={batch_size})"
            )
        )

        # Find entries where the unified_document is None but not marked as deleted
        entries_to_update = UserSavedEntry.objects.filter(
            unified_document__isnull=True, document_deleted=False, is_removed=False
        )

        total_entries = entries_to_update.count()
        self.stdout.write(f"Found {total_entries} entries to update")

        if total_entries == 0:
            self.stdout.write(self.style.SUCCESS("No entries to clean up"))
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: Would mark {total_entries} entries as deleted"
                )
            )
            return

        # Process in batches
        processed = 0
        with transaction.atomic():
            for i in range(0, total_entries, batch_size):
                # Get IDs for this batch
                batch_ids = list(
                    entries_to_update[i : i + batch_size].values_list("id", flat=True)
                )

                # Update the batch by ID
                UserSavedEntry.objects.filter(id__in=batch_ids).update(
                    document_deleted=True, document_deleted_date=timezone.now()
                )

                processed += len(batch_ids)
                self.stdout.write(f"Processed {processed}/{total_entries} entries")

        self.stdout.write(
            self.style.SUCCESS(f"Successfully cleaned up {processed} entries")
        )
