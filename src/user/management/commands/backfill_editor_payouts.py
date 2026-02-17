import datetime
import math
from calendar import monthrange

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db.models import F

from purchase.related_models.constants.rsc_exchange_currency import COIN_GECKO
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.distributions import Distribution
from reputation.related_models.distribution import Distribution as DistributionModel
from researchhub_access_group.constants import (
    ASSISTANT_EDITOR,
    ASSOCIATE_EDITOR,
    SENIOR_EDITOR,
)
from user.constants.gatekeeper_constants import (
    EDITOR_PAYOUT_ADMIN,
    PAYOUT_EXCLUSION_LIST,
)
from user.editor_payout_tasks import (
    ASSISTANT_EDITOR_USD_PAY_AMOUNT_PER_MONTH,
    ASSOCIATE_EDITOR_USD_PAY_AMOUNT_PER_MONTH,
    SENIOR_EDITOR_USD_PAY_AMOUNT_PER_MONTH,
    USD_PER_RSC_PRICE_FLOOR,
)
from user.related_models.gatekeeper_model import Gatekeeper


class Command(BaseCommand):
    help = (
        "Backfill editor payouts for days that were missed. "
        "Uses each day's exchange rate if available, otherwise the latest rate."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "start_date",
            type=str,
            help="Start date (inclusive) in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "end_date",
            type=str,
            help="End date (inclusive) in YYYY-MM-DD format.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be paid without writing to the database.",
        )

    def handle(self, *args, **options):
        start = datetime.datetime.strptime(options["start_date"], "%Y-%m-%d").date()
        end = datetime.datetime.strptime(options["end_date"], "%Y-%m-%d").date()
        dry_run = options["dry_run"]

        if end >= datetime.date.today():
            self.stderr.write(self.style.ERROR("end_date must be in the past."))
            return

        if start > end:
            self.stderr.write(self.style.ERROR("start_date must be <= end_date."))
            return

        # Find days that already have payouts
        existing = set(
            DistributionModel.objects.filter(
                distribution_type="EDITOR_PAYOUT",
                created_date__date__gte=start,
                created_date__date__lte=end,
            )
            .values_list("created_date__date", flat=True)
            .distinct()
        )

        missing_days = []
        current = start
        while current <= end:
            if current not in existing:
                missing_days.append(current)
            current += datetime.timedelta(days=1)

        if not missing_days:
            self.stdout.write(self.style.SUCCESS("No missing payout days found."))
            return

        self.stdout.write(
            f"Found {len(missing_days)} missing day(s): "
            f"{missing_days[0]} to {missing_days[-1]}"
        )

        # Get fallback (latest) exchange rate
        fallback_rate = (
            RscExchangeRate.objects.filter(
                price_source=COIN_GECKO,
            )
            .order_by("-created_date")
            .first()
        )

        if fallback_rate is None:
            self.stderr.write(self.style.ERROR("No CoinGecko exchange rate found."))
            return

        self.stdout.write(
            f"Fallback exchange rate: {fallback_rate.real_rate} USD/RSC "
            f"from {fallback_rate.created_date}"
        )

        # Get editors
        User = apps.get_model("user.User")
        excluded_emails = Gatekeeper.objects.filter(
            type__in=[EDITOR_PAYOUT_ADMIN, PAYOUT_EXCLUSION_LIST]
        ).values_list("email", flat=True)

        editors = (
            User.objects.editors()
            .exclude(email__in=excluded_emails)
            .annotate(editor_type=F("permissions__access_type"))
        )

        editor_count = editors.count()
        self.stdout.write(
            f"Paying {editor_count} editor(s) for {len(missing_days)} day(s)"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be made."))

        from reputation.distributor import Distributor

        total_distributed = 0

        for day in missing_days:
            # Use that day's rate if it exists, otherwise fall back to latest
            day_rate = (
                RscExchangeRate.objects.filter(
                    price_source=COIN_GECKO,
                    created_date__date=day,
                )
                .order_by("-created_date")
                .first()
            )

            rate_record = day_rate or fallback_rate
            usd_per_rsc = max(rate_record.real_rate, USD_PER_RSC_PRICE_FLOOR)
            rate_source = "day's rate" if day_rate else "fallback"
            self.stdout.write(f"  {day}: using {rate_source} — {usd_per_rsc} USD/RSC")

            num_days_in_month = monthrange(day.year, day.month)[1]
            pay_amounts = {
                SENIOR_EDITOR: (
                    SENIOR_EDITOR_USD_PAY_AMOUNT_PER_MONTH
                    / usd_per_rsc
                    / num_days_in_month
                ),
                ASSOCIATE_EDITOR: (
                    ASSOCIATE_EDITOR_USD_PAY_AMOUNT_PER_MONTH
                    / usd_per_rsc
                    / num_days_in_month
                ),
                ASSISTANT_EDITOR: (
                    ASSISTANT_EDITOR_USD_PAY_AMOUNT_PER_MONTH
                    / usd_per_rsc
                    / num_days_in_month
                ),
            }

            day_count = 0
            for editor in editors.iterator():
                pay_amount = pay_amounts.get(
                    editor.editor_type,
                    pay_amounts[ASSISTANT_EDITOR],
                )

                if dry_run:
                    self.stdout.write(
                        f"  [DRY RUN] {day} | {editor.email} | "
                        f"{editor.editor_type} | {pay_amount:.2f} RSC"
                    )
                else:
                    distributor = Distributor(
                        Distribution("EDITOR_PAYOUT", pay_amount, False),
                        editor,
                        None,
                        day,
                    )
                    distributor.distribute()

                day_count += 1
                total_distributed += pay_amount

            self.stdout.write(f"  {day}: paid {day_count} editor(s)")

        self.stdout.write(
            self.style.SUCCESS(
                f"{'[DRY RUN] ' if dry_run else ''}"
                f"Done. {len(missing_days)} day(s), "
                f"{total_distributed:,.2f} total RSC distributed."
            )
        )
