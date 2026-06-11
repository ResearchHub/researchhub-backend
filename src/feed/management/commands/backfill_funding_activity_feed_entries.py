from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from user.related_models.funding_activity_model import FundingActivity


class Command(BaseCommand):
    help = "Backfill FeedEntry rows for existing bounty payouts and review tips"

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
                self.stdout.write(
                    f"Filtering activities with activity_date since {options['since']}"
                )
            except ValueError:
                self.stderr.write("Invalid date format. Use YYYY-MM-DD.")
                return

        processed, skipped, errors = self._backfill_funding_activities(
            since_dt, options["dry_run"]
        )

        self.stdout.write(
            f"Funding activities: processed={processed}, "
            f"skipped={skipped}, errors={errors}"
        )

    def _backfill_funding_activities(self, since_dt, dry_run):
        activity_ct = ContentType.objects.get_for_model(FundingActivity)

        queryset = (
            FundingActivity.objects.filter(
                source_type__in=[
                    FundingActivity.BOUNTY_PAYOUT,
                    FundingActivity.TIP_REVIEW,
                ],
            )
            .select_related("funder", "unified_document")
            .order_by("id")
        )

        if since_dt:
            queryset = queryset.filter(activity_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(f"Found {total} funding activities to process")

        if total == 0 or dry_run:
            if dry_run and total > 0:
                self.stdout.write(f"Dry run: would backfill {total} funding activities")
            return (0, 0, 0)

        processed = 0
        skipped = 0
        errors = 0

        for activity in queryset.iterator(chunk_size=500):
            try:
                unified_doc = activity.unified_document
                if not unified_doc:
                    skipped += 1
                    continue

                hub_ids = list(unified_doc.hubs.values_list("id", flat=True))

                create_feed_entry(
                    item_id=activity.id,
                    item_content_type_id=activity_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=activity.funder_id,
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(f"Error on funding activity {activity.id}: {e}")

        return (processed, skipped, errors)
