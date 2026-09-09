"""Create empty FundingPool rows for grants that do not have one.

Run from the repository root:

    cd src && uv run python manage.py backfill_grant_funding_pools --dry-run
    cd src && uv run python manage.py backfill_grant_funding_pools
"""

from django.core.management.base import BaseCommand

from purchase.models import FundingPool, Grant


class Command(BaseCommand):
    help = "Create empty FundingPool rows for grants that do not have one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Count grants that would get a pool without creating any.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        grants = Grant.objects.filter(funding_pool__isnull=True).only(
            "id", "created_by_id"
        )
        total = grants.count()
        self.stdout.write(f"Found {total} grants without a funding pool.")

        if dry_run or total == 0:
            return

        pools = [
            FundingPool(grant_id=grant.id, created_by_id=grant.created_by_id)
            for grant in grants.iterator()
        ]
        FundingPool.objects.bulk_create(pools)

        self.stdout.write(
            self.style.SUCCESS(f"Created {len(pools)} empty funding pools.")
        )
