from django.core.management.base import BaseCommand

from purchase.models import Purchase, RscExchangeRate

BATCH_SIZE = 500


class Command(BaseCommand):
    help = "Backfill rsc_usd_rate on purchases with historical rates."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate, don't update.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        purchases = Purchase.objects.filter(rsc_usd_rate__isnull=True)
        total = purchases.count()
        self.stdout.write(f"Found {total} purchases without rate.")

        if dry_run or total == 0:
            return

        updated = 0
        skipped = 0
        batch = []

        for purchase in purchases.iterator():
            rate_record = (
                RscExchangeRate.objects.filter(
                    created_date__lte=purchase.created_date,
                    target_currency="USD",
                )
                .order_by("-created_date")
                .first()
            )

            if rate_record is None:
                skipped += 1
                continue

            purchase.rsc_usd_rate = rate_record.rate
            batch.append(purchase)

            if len(batch) >= BATCH_SIZE:
                Purchase.objects.bulk_update(batch, ["rsc_usd_rate"])
                updated += len(batch)
                self.stdout.write(f"  Updated {updated}/{total}...")
                batch = []

        if batch:
            Purchase.objects.bulk_update(batch, ["rsc_usd_rate"])
            updated += len(batch)

        self.stdout.write(f"Updated: {updated}, skipped (no rate): {skipped}.")
