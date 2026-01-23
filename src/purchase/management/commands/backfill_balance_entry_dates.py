"""
Backfills BalanceEntryDate records for existing positive Balance records.

This is a one-time migration to enable staking calculations for users
who already have RSC in their accounts.

Usage:
    python manage.py backfill_balance_entry_dates
    python manage.py backfill_balance_entry_dates --dry-run
    python manage.py backfill_balance_entry_dates --batch-size=500
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from purchase.models import Balance, BalanceEntryDate


class Command(BaseCommand):
    help = "Backfill BalanceEntryDate records for existing positive Balance records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created without actually creating records",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of records to process in each batch (default: 1000)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN - no records will be created"))

        # Get all positive Balance records that don't already have an entry date
        existing_balance_ids = BalanceEntryDate.objects.values_list(
            "balance_id", flat=True
        )

        # Find all positive balances without entry dates
        positive_balances = Balance.objects.exclude(
            id__in=existing_balance_ids
        ).filter(
            amount__gt="0"  # Filter for positive amounts (stored as strings)
        ).select_related("user").order_by("created_date")

        total_count = positive_balances.count()
        self.stdout.write(f"Found {total_count} positive Balance records to process")

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("No records to backfill"))
            return

        created_count = 0
        error_count = 0

        # Process in batches
        for offset in range(0, total_count, batch_size):
            batch = list(positive_balances[offset : offset + batch_size])
            self.stdout.write(
                f"Processing batch {offset // batch_size + 1} "
                f"({offset + 1}-{min(offset + batch_size, total_count)} of {total_count})"
            )

            entries_to_create = []

            for balance in batch:
                try:
                    amount = Decimal(balance.amount)
                    if amount <= 0:
                        continue

                    entry = BalanceEntryDate(
                        user=balance.user,
                        balance=balance,
                        entry_date=balance.created_date,
                        original_amount=amount,
                        remaining_amount=amount,
                    )
                    entries_to_create.append(entry)

                except Exception as e:
                    error_count += 1
                    self.stderr.write(
                        self.style.ERROR(f"Error processing balance {balance.id}: {e}")
                    )

            if entries_to_create and not dry_run:
                with transaction.atomic():
                    BalanceEntryDate.objects.bulk_create(
                        entries_to_create,
                        ignore_conflicts=True,  # Skip if already exists
                    )

                created_count += len(entries_to_create)
            elif entries_to_create:
                created_count += len(entries_to_create)
                self.stdout.write(
                    f"  Would create {len(entries_to_create)} BalanceEntryDate records"
                )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"DRY RUN complete. Would create {created_count} records. "
                    f"{error_count} errors."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backfill complete. Created {created_count} records. "
                    f"{error_count} errors."
                )
            )
