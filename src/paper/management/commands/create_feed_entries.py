from datetime import datetime

from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.utils import timezone

from feed.models import FeedEntry
from paper.models import Paper


class Command(BaseCommand):
    help = "Creates feed entries from the first 100 papers"

    def handle(self, *args, **options):
        papers = (
            Paper.objects.select_related("uploaded_by", "unified_document")
            .prefetch_related("unified_document__hubs")
            .order_by("-paper_publish_date")[:100]
        )

        created_count = 0
        attached_hubs = 0
        paper_ct = ContentType.objects.get_for_model(Paper)

        for paper in papers:
            ud = paper.unified_document

            if not ud:
                continue

            # Prefer timezone-aware datetime
            if paper.paper_publish_date:
                action_dt = datetime.combine(
                    paper.paper_publish_date,
                    datetime.min.time(),
                    tzinfo=timezone.get_current_timezone(),
                )
            else:
                action_dt = getattr(paper, "created_date", timezone.now())

            # One FeedEntry per paper/action/user, hubs are attached via M2M
            entry, created = FeedEntry.objects.get_or_create(
                content_type=paper_ct,
                object_id=paper.id,
                action="PUBLISH",
                user=None,
                defaults={"action_date": action_dt, "unified_document": ud},
            )

            if created:
                created_count += 1
            else:  # For idempotency
                to_update = []

                if entry.action_date != action_dt:
                    entry.action_date = action_dt

                    to_update.append("action_date")

                if entry.unified_document_id != ud.id:
                    entry.unified_document = ud

                    to_update.append("unified_document")

                if to_update:
                    entry.save(update_fields=to_update)

            # Attach hubs (idempotent)
            hubs_qs = ud.hubs.all()

            if hubs_qs.exists():
                before = entry.hubs.count()

                entry.hubs.add(*hubs_qs)  # duplicates ignored

                after = entry.hubs.count()

                attached_hubs += max(0, after - before)

        if created_count:
            self.stdout.write(
                self.style.SUCCESS(f"Created {created_count} feed entries")
            )
        else:
            self.stdout.write(self.style.WARNING("No new feed entries were created"))

        if attached_hubs:
            self.stdout.write(self.style.SUCCESS(f"Attached {attached_hubs} hub links"))
        else:
            self.stdout.write(self.style.WARNING("No hub links were attached"))
