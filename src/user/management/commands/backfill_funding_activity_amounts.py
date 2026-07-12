from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from purchase.models import Purchase
from purchase.related_models.usd_fundraise_contribution_model import (
    UsdFundraiseContribution,
)
from user.related_models.funding_activity_model import (
    FundingActivity,
    FundingActivityRecipient,
)
from user.services.funding_activity_service import FundingActivityService

BATCH_SIZE = 500

PURCHASE_SOURCE_TYPES = {
    FundingActivity.FUNDRAISE_PAYOUT,
    FundingActivity.TIP_DOCUMENT,
}

HISTORICAL_RATE_SOURCE_TYPES = {
    FundingActivity.BOUNTY_PAYOUT,
    FundingActivity.TIP_REVIEW,
    FundingActivity.FEE,
}


class Command(BaseCommand):
    help = (
        "Populate total_usd_cents / amount_usd_cents (and calculated RSC for USD "
        "sources) on existing "
        "FundingActivity rows, and create missing USD_FUNDRAISE_PAYOUT activities."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing to the database.",
        )
        parser.add_argument(
            "--log-freq",
            type=int,
            default=500,
            help="Log progress every N items (default: 500).",
        )
        parser.add_argument(
            "--skip-usd-fundraise",
            action="store_true",
            help=(
                "Only populate amounts on existing rows; skip creating "
                "USD_FUNDRAISE_PAYOUT."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        log_freq = options["log_freq"]
        skip_usd_fundraise = options["skip_usd_fundraise"]

        if dry_run:
            self.stdout.write("DRY RUN: no changes will be written.")

        updated, skipped, errors = self._populate_existing_amounts(dry_run, log_freq)
        self.stdout.write(
            f"Phase 1 (populate amounts): updated={updated} "
            f"skipped={skipped} errors={errors}"
        )

        if skip_usd_fundraise:
            self.stdout.write("Skipping Phase 2 (--skip-usd-fundraise).")
            return

        created, usd_skipped, usd_errors, would_create = (
            self._create_usd_fundraise_rows(dry_run, log_freq)
        )
        if dry_run:
            self.stdout.write(
                f"Phase 2 (USD fundraise): would_create={would_create} "
                f"skipped={usd_skipped} errors={usd_errors}"
            )
        else:
            self.stdout.write(
                f"Phase 2 (USD fundraise): created={created} "
                f"skipped={usd_skipped} errors={usd_errors}"
            )

    def _populate_existing_amounts(self, dry_run, log_freq):
        """Phase 1: set dual amounts on activities where total_usd_cents is still 0."""
        qs = (
            FundingActivity.objects.filter(total_usd_cents=0)
            .prefetch_related("recipients")
            .order_by("pk")
        )
        total = qs.count()
        self.stdout.write(f"Phase 1: {total} activity row(s) with total_usd_cents=0.")

        updated = 0
        skipped = 0
        errors = 0
        activity_batch = []
        recipient_batch = []

        for i, activity in enumerate(qs.iterator(chunk_size=BATCH_SIZE), start=1):
            try:
                recipients = list(activity.recipients.all())
                populated = self._populate_amounts_for_activity(activity, recipients)
                if not populated:
                    skipped += 1
                    continue

                if dry_run:
                    updated += 1
                else:
                    activity_batch.append(activity)
                    recipient_batch.extend(recipients)

                    if len(activity_batch) >= BATCH_SIZE:
                        self._flush_amount_batches(activity_batch, recipient_batch)
                        updated += len(activity_batch)
                        activity_batch = []
                        recipient_batch = []
            except Exception as e:
                errors += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  activity pk={activity.pk} ({activity.source_type}): {e}"
                    )
                )

            if i % log_freq == 0:
                self.stdout.write(
                    f"  Phase 1: {i}/{total} "
                    f"(updated={updated} skipped={skipped} errors={errors})"
                )

        if not dry_run and activity_batch:
            self._flush_amount_batches(activity_batch, recipient_batch)
            updated += len(activity_batch)

        return updated, skipped, errors

    def _populate_amounts_for_activity(self, activity, recipients):
        """
        Populate dual amounts on activity and recipients.
        Returns True when amounts were computed; False when skipped (no rate/source).
        """
        if activity.source_type == FundingActivity.USD_FUNDRAISE_PAYOUT:
            source = activity.source
            if source is None:
                return False
            rate = FundingActivityService._get_historical_rsc_usd_rate(
                activity.activity_date
            )
            FundingActivityService._populate_usd_native_dual_amounts_on_recipients(
                activity,
                recipients,
                source.amount_cents,
                rate,
            )
            # Native USD cents are always set; RSC leg requires a rate.
            return True

        rate = self._resolve_rate_for_activity(activity)
        if rate is None:
            FundingActivityService._populate_dual_amounts_on_recipients(
                activity, recipients, None
            )
            return False

        FundingActivityService._populate_dual_amounts_on_recipients(
            activity, recipients, rate
        )
        return True

    def _resolve_rate_for_activity(self, activity):
        source = activity.source
        if source is None:
            return None

        if activity.source_type in PURCHASE_SOURCE_TYPES:
            if not isinstance(source, Purchase):
                return None
            return FundingActivityService._resolve_rate_for_purchase(source)

        if activity.source_type in HISTORICAL_RATE_SOURCE_TYPES:
            return FundingActivityService._get_historical_rsc_usd_rate(
                activity.activity_date
            )

        return None

    def _flush_amount_batches(self, activities, recipients):
        FundingActivity.objects.bulk_update(
            activities, ["total_usd_cents", "total_amount"]
        )
        if recipients:
            FundingActivityRecipient.objects.bulk_update(
                recipients, ["amount_usd_cents", "amount"]
            )

    def _create_usd_fundraise_rows(self, dry_run, log_freq):
        """Phase 2: create missing USD_FUNDRAISE_PAYOUT activities."""
        ct_contribution = ContentType.objects.get_for_model(UsdFundraiseContribution)
        existing_source_ids = set(
            FundingActivity.objects.filter(
                source_type=FundingActivity.USD_FUNDRAISE_PAYOUT,
                source_content_type=ct_contribution,
            ).values_list("source_object_id", flat=True)
        )

        qs = FundingActivityService.get_usd_fundraise_payouts().order_by("pk")
        total = qs.count()
        self.stdout.write(f"Phase 2: {total} USD contribution source(s).")

        created = 0
        skipped = 0
        errors = 0
        would_create = 0

        for i, contribution in enumerate(qs.iterator(), start=1):
            if contribution.pk in existing_source_ids:
                skipped += 1
                if i % log_freq == 0:
                    self.stdout.write(
                        f"  Phase 2: {i}/{total} "
                        f"(created={created} skipped={skipped} errors={errors})"
                    )
                continue

            if dry_run:
                would_create += 1
            else:
                try:
                    activity = FundingActivityService.create_funding_activity(
                        FundingActivity.USD_FUNDRAISE_PAYOUT,
                        contribution,
                    )
                    if activity is not None:
                        created += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.WARNING(f"  contribution pk={contribution.pk}: {e}")
                    )

            if i % log_freq == 0:
                label = "would_create" if dry_run else "created"
                count = would_create if dry_run else created
                self.stdout.write(
                    f"  Phase 2: {i}/{total} "
                    f"({label}={count} skipped={skipped} errors={errors})"
                )

        return created, skipped, errors, would_create
