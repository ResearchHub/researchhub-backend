from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.signals.funding_activity_signals import FINANCIAL_FEED_SOURCE_TYPES
from feed.tasks import create_feed_entry
from user.related_models.funding_activity_model import FundingActivity


class Command(BaseCommand):
    help = (
        "Backfill FeedEntry rows for existing bounty payout and review tip "
        "FundingActivities"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only backfill activities after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Count eligible activities without creating entries.",
        )

    def handle(self, *args, **options):
        since_dt = None
        if options["since"]:
            try:
                since_dt = datetime.strptime(options["since"], "%Y-%m-%d")
                since_dt = timezone.make_aware(since_dt)
                self.stdout.write(f"Filtering activities since {options['since']}")
            except ValueError:
                self.stderr.write("Invalid date format. Use YYYY-MM-DD.")
                return

        fa_ct = ContentType.objects.get_for_model(FundingActivity)
        queryset = (
            FundingActivity.objects.filter(
                source_type__in=FINANCIAL_FEED_SOURCE_TYPES,
            )
            .select_related("funder", "unified_document")
            .order_by("id")
        )

        if since_dt:
            queryset = queryset.filter(activity_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(
            f"Found {total} bounty payout and review tip activities to process"
        )

        if total == 0:
            return

        if options["dry_run"]:
            self.stdout.write(f"Dry run: would backfill {total} activities")
            return

        processed = 0
        skipped = 0
        errors = 0

        for activity in queryset.iterator(chunk_size=500):
            try:
                if activity.unified_document_id:
                    hub_ids = list(
                        activity.unified_document.hubs.values_list("id", flat=True)
                    )
                else:
                    hub_ids = []

                create_feed_entry(
                    item_id=activity.id,
                    item_content_type_id=fa_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=activity.funder_id,
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(f"Error on FundingActivity {activity.id}: {e}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: processed={processed}, skipped={skipped}, errors={errors}"
            )
        )
