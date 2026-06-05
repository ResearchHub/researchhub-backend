from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from feed.tasks import create_feed_entry, serialize_feed_item
from researchhub_comment.related_models.rh_comment_model import RhCommentModel


class Command(BaseCommand):
    help = "Backfill or refresh FeedEntry rows for existing comments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--since",
            type=str,
            default=None,
            help="Only process entries after this date (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Count eligible entries without making changes.",
        )
        parser.add_argument(
            "--refresh",
            action="store_true",
            default=False,
            help="Refresh content and metrics on existing comment feed entries "
            "instead of creating new ones.",
        )

    def _parse_since(self, since_str):
        try:
            return timezone.make_aware(datetime.strptime(since_str, "%Y-%m-%d"))
        except ValueError:
            self.stderr.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD."))
            return None

    def handle(self, *args, **options):
        if options["refresh"]:
            self._handle_refresh(**options)
        else:
            self._handle_backfill(**options)

    def _handle_refresh(self, **options):
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        queryset = FeedEntry.objects.filter(content_type=comment_ct).order_by("id")

        if options["since"]:
            since_dt = self._parse_since(options["since"])
            if not since_dt:
                return
            queryset = queryset.filter(action_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(f"Found {total} comment feed entries to refresh")

        if total == 0 or options["dry_run"]:
            return

        processed = skipped = errors = 0

        for entry in queryset.iterator(chunk_size=500):
            try:
                if not entry.item:
                    skipped += 1
                    continue

                content = serialize_feed_item(entry.item, entry.content_type)
                if content is None:
                    skipped += 1
                    continue

                entry.content = content
                entry.metrics = serialize_feed_metrics(entry.item, entry.content_type)
                entry.save(update_fields=["content", "metrics"])
                processed += 1

                if processed % 100 == 0:
                    self.stdout.write(f"Refreshed {processed}/{total}")
            except Exception as e:
                errors += 1
                self.stderr.write(
                    self.style.ERROR(f"Error on feed entry {entry.id}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: refreshed={processed}, skipped={skipped}, errors={errors}"
            )
        )

    def _handle_backfill(self, **options):
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        queryset = (
            RhCommentModel.objects.filter(is_removed=False)
            .select_related("thread__content_type", "created_by")
            .order_by("id")
        )

        if options["since"]:
            since_dt = self._parse_since(options["since"])
            if not since_dt:
                return
            queryset = queryset.filter(created_date__gte=since_dt)

        total = queryset.count()
        self.stdout.write(f"Found {total} comments to backfill")

        if total == 0 or options["dry_run"]:
            return

        processed = skipped = errors = 0

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

                create_feed_entry(
                    item_id=comment.id,
                    item_content_type_id=comment_ct.id,
                    action=FeedEntry.PUBLISH,
                    hub_ids=hub_ids,
                    user_id=comment.created_by_id or None,
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
                f"Done: processed={processed}, skipped={skipped}, errors={errors}"
            )
        )
