from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from purchase.models import Fundraise
from purchase.related_models.purchase_model import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)


class Command(BaseCommand):
    help = "Backfill FeedEntry rows for existing fundraise contributions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only backfill contributions created after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Count eligible contributions without creating entries.",
        )

    def handle(self, *args, **options):
        since_dt = None
        if options["since"]:
            try:
                since_dt = datetime.strptime(options["since"], "%Y-%m-%d")
                since_dt = timezone.make_aware(since_dt)
                self.stdout.write(
                    f"Filtering contributions created since {options['since']}"
                )
            except ValueError:
                self.stderr.write("Invalid date format. Use YYYY-MM-DD.")
                return

        rsc_stats = self._backfill_rsc_contributions(since_dt, options["dry_run"])
        usd_stats = self._backfill_usd_contributions(since_dt, options["dry_run"])

        self.stdout.write(
            f"RSC contributions: processed={rsc_stats[0]}, "
            f"skipped={rsc_stats[1]}, errors={rsc_stats[2]}"
        )
        self.stdout.write(
            f"USD contributions: processed={usd_stats[0]}, "
            f"skipped={usd_stats[1]}, errors={usd_stats[2]}"
        )

    def _backfill_rsc_contributions(self, since_dt, dry_run):
        purchase_ct = ContentType.objects.get_for_model(Purchase)

        queryset = (
            Purchase.objects.filter(
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            )
            .select_related("user")
            .order_by("id")
        )

        if since_dt:
            queryset = queryset.filter(created_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(f"Found {total} RSC contributions to process")

        if total == 0 or dry_run:
            if dry_run and total > 0:
                self.stdout.write(f"Dry run: would backfill {total} RSC contributions")
            return (0, 0, 0)

        processed = 0
        skipped = 0
        errors = 0

        for purchase in queryset.iterator(chunk_size=500):
            try:

                try:
                    fundraise = Fundraise.objects.select_related(
                        "unified_document"
                    ).get(id=purchase.object_id)
                except Fundraise.DoesNotExist:
                    skipped += 1
                    continue

                unified_doc = fundraise.unified_document
                if not unified_doc:
                    skipped += 1
                    continue

                hub_ids = list(unified_doc.hubs.values_list("id", flat=True))

                create_feed_entry(
                    item_id=purchase.id,
                    item_content_type_id=purchase_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=purchase.user_id,
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"RSC: Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(f"Error on purchase {purchase.id}: {e}")

        return (processed, skipped, errors)

    def _backfill_usd_contributions(self, since_dt, dry_run):
        usd_ct = ContentType.objects.get_for_model(UsdFundraiseContribution)

        queryset = (
            UsdFundraiseContribution.objects.filter(
                is_refunded=False,
            )
            .select_related("user", "fundraise__unified_document")
            .order_by("id")
        )

        if since_dt:
            queryset = queryset.filter(created_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(f"Found {total} USD contributions to process")

        if total == 0 or dry_run:
            if dry_run and total > 0:
                self.stdout.write(f"Dry run: would backfill {total} USD contributions")
            return (0, 0, 0)

        processed = 0
        skipped = 0
        errors = 0

        for contribution in queryset.iterator(chunk_size=500):
            try:
                unified_doc = contribution.fundraise.unified_document
                if not unified_doc:
                    skipped += 1
                    continue

                hub_ids = list(unified_doc.hubs.values_list("id", flat=True))

                create_feed_entry(
                    item_id=contribution.id,
                    item_content_type_id=usd_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=contribution.user_id,
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"USD: Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(f"Error on USD contribution {contribution.id}: {e}")

        return (processed, skipped, errors)
