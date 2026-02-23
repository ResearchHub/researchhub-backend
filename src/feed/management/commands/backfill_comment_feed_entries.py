from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.tasks import create_feed_entry
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


class Command(BaseCommand):
    help = "Backfill FeedEntry rows for existing comments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only backfill comments created after this date " "(YYYY-MM-DD).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Count eligible comments without creating entries.",
        )

    def handle(self, *args, **options):
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        queryset = (
            RhCommentModel.objects.filter(
                is_removed=False,
            )
            .select_related(
                "thread__content_type",
                "created_by",
            )
            .order_by("id")
        )

        if options["since"]:
            try:
                since_dt = datetime.strptime(options["since"], "%Y-%m-%d")
                since_dt = timezone.make_aware(since_dt)
                queryset = queryset.filter(created_date__gte=since_dt)
                self.stdout.write(
                    f"Filtering comments created since " f"{options['since']}"
                )
            except ValueError:
                self.stderr.write(
                    self.style.ERROR("Invalid date format. Use YYYY-MM-DD.")
                )
                return

        total = queryset.count()
        self.stdout.write(f"Found {total} comments to process")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No comments to backfill"))
            return

        if options["dry_run"]:
            self.stdout.write(
                self.style.SUCCESS(f"Dry run: would backfill {total} comments")
            )
            return

        processed = 0
        skipped = 0
        errors = 0

        for comment in queryset.iterator(chunk_size=500):
            try:
                unified_doc = getattr(comment, "unified_document", None)
                if unified_doc is None:
                    try:
                        unified_doc = comment.thread.unified_document
                    except Exception:
                        skipped += 1
                        continue

                if not unified_doc:
                    skipped += 1
                    continue

                hub_ids = list(unified_doc.hubs.values_list("id", flat=True))
                user_id = comment.created_by_id if comment.created_by_id else None

                create_feed_entry(
                    item_id=comment.id,
                    item_content_type_id=comment_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=user_id,
                )
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"Processed {processed}/{total}")

            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Error on comment {comment.id}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: processed={processed}, " f"skipped={skipped}, errors={errors}"
            )
        )
