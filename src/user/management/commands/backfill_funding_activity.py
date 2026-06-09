from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from user.related_models.funding_activity_model import FundingActivity
from user.services.funding_activity_service import FundingActivityService


class Command(BaseCommand):
    help = (
        "Backfill FundingActivity and FundingActivityRecipient from historical "
        "Purchases, EscrowRecipients, and Distributions. Idempotent: skips "
        "sources that already have a FundingActivity."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log what would be created without writing to the database.",
        )
        parser.add_argument(
            "--log-freq",
            type=int,
            default=500,
            help="Log progress every N items (default: 500).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        log_freq = options["log_freq"]

        if dry_run:
            self.stdout.write("DRY RUN: no changes will be written.")

        total_created = 0
        total_skipped = 0
        total_errors = 0
        total_would_create = 0

        # 1. Fundraise payouts (Purchase FUNDRAISE_CONTRIBUTION, paid, escrow PAID)
        created, skipped, errors, would_create = self._backfill_fundraise_payouts(
            dry_run, log_freq
        )
        total_created += created
        total_skipped += skipped
        total_errors += errors
        total_would_create += would_create

        # 2. Bounty payouts (EscrowRecipients, PAID escrow, REVIEW bounty)
        c, s, e, wc = self._backfill_bounty_payouts(dry_run, log_freq)
        total_created += c
        total_skipped += s
        total_errors += e
        total_would_create += wc

        # 3. Document tips (Purchase BOOST on paper/post, paid)
        c, s, e, wc = self._backfill_document_tips(dry_run, log_freq)
        total_created += c
        total_skipped += s
        total_errors += e
        total_would_create += wc

        # 4. Review tips (Distribution PURCHASE for review comments)
        c, s, e, wc = self._backfill_review_tips(dry_run, log_freq)
        total_created += c
        total_skipped += s
        total_errors += e
        total_would_create += wc

        # 5. Fees (Distribution BOUNTY_DAO_FEE, BOUNTY_RH_FEE, SUPPORT_RH_FEE)
        c, s, e, wc = self._backfill_fees(dry_run, log_freq)
        total_created += c
        total_skipped += s
        total_errors += e
        total_would_create += wc

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry run complete. would_create={total_would_create} "
                    f"skipped={total_skipped} errors={total_errors}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Backfill complete. created={total_created} "
                    f"skipped={total_skipped} errors={total_errors}"
                )
            )

    def _backfill_fundraise_payouts(self, dry_run, log_freq):
        label = "fundraise_payouts"
        qs = FundingActivityService.get_fundraise_payouts().order_by("pk")
        return self._backfill_source(
            label,
            qs,
            FundingActivity.FUNDRAISE_PAYOUT,
            dry_run,
            log_freq,
        )

    def _backfill_bounty_payouts(self, dry_run, log_freq):
        label = "bounty_payouts"
        qs = FundingActivityService.get_bounty_payouts().order_by("pk")
        return self._backfill_source(
            label,
            qs,
            FundingActivity.BOUNTY_PAYOUT,
            dry_run,
            log_freq,
        )

    def _backfill_document_tips(self, dry_run, log_freq):
        label = "document_tips"
        qs = FundingActivityService.get_document_tips().order_by("pk")
        return self._backfill_source(
            label,
            qs,
            FundingActivity.TIP_DOCUMENT,
            dry_run,
            log_freq,
        )

    def _backfill_review_tips(self, dry_run, log_freq):
        label = "review_tips"
        qs = FundingActivityService.get_review_tips().order_by("pk")
        return self._backfill_source(
            label,
            qs,
            FundingActivity.TIP_REVIEW,
            dry_run,
            log_freq,
        )

    def _backfill_fees(self, dry_run, log_freq):
        label = "fees"
        qs = FundingActivityService.get_fees().order_by("pk")
        return self._backfill_source(
            label,
            qs,
            FundingActivity.FEE,
            dry_run,
            log_freq,
        )

    def _backfill_source(
        self,
        label,
        queryset,
        source_type,
        dry_run,
        log_freq,
    ):
        """Process a queryset of source objects; create FundingActivity per item."""
        content_type = ContentType.objects.get_for_model(queryset.model)
        existing_source_ids = set(
            FundingActivity.objects.filter(
                source_type=source_type,
                source_content_type=content_type,
            ).values_list("source_object_id", flat=True)
        )

        created = 0
        skipped = 0
        errors = 0
        would_create = 0
        total = queryset.count()
        self.stdout.write(f"Backfilling {label}: {total} source(s).")

        for i, obj in enumerate(queryset.iterator(), start=1):
            if obj.pk in existing_source_ids:
                skipped += 1
                if i % log_freq == 0:
                    self._log_backfill_progress(
                        label, i, total, dry_run, created, skipped, errors, would_create
                    )
                continue

            if dry_run:
                would_create += 1
            else:
                try:
                    activity = FundingActivityService.create_funding_activity(
                        source_type=source_type,
                        source_object=obj,
                    )
                    if activity is not None:
                        created += 1
                    else:
                        skipped += 1
                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {label} pk={getattr(obj, 'pk', '?')}: {e}"
                        )
                    )

            if i % log_freq == 0:
                self._log_backfill_progress(
                    label, i, total, dry_run, created, skipped, errors, would_create
                )

        self._log_backfill_phase_summary(
            label, dry_run, created, skipped, errors, would_create
        )
        return created, skipped, errors, would_create

    def _log_backfill_progress(
        self, label, i, total, dry_run, created, skipped, errors, would_create
    ):
        if dry_run:
            self.stdout.write(
                f"  {label}: {i}/{total} "
                f"(would_create={would_create} skipped={skipped} errors={errors})"
            )
        else:
            self.stdout.write(
                f"  {label}: {i}/{total} "
                f"(created={created} skipped={skipped} errors={errors})"
            )

    def _log_backfill_phase_summary(
        self, label, dry_run, created, skipped, errors, would_create
    ):
        if dry_run:
            self.stdout.write(
                f"  {label}: would_create={would_create} "
                f"skipped={skipped} errors={errors}"
            )
        else:
            self.stdout.write(
                f"  {label}: created={created} skipped={skipped} errors={errors}"
            )
