from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper


class Command(BaseCommand):
    help = "Populates feed entries with the first 100 papers"

    def handle(self, *args, **options):
        # Get first 100 papers, ordered by newest first
        papers = (
            Paper.objects.select_related("uploaded_by")
            .prefetch_related("hubs")
            .order_by("-paper_publish_date")[:100]
        )
        paper_content_type = ContentType.objects.get_for_model(Paper)
        hub_content_type = ContentType.objects.get_for_model(Hub)

        feed_entries = []
        created_count = 0

        for paper in papers:
            # For each paper's hubs, create a feed entry
            for hub in paper.hubs.all():
                # Check if entry already exists to avoid duplicates
                exists = FeedEntry.objects.filter(
                    content_type=paper_content_type,
                    object_id=paper.id,
                    parent_content_type=hub_content_type,
                    parent_object_id=hub.id,
                    action="PUBLISH",
                ).exists()

                if not exists:
                    feed_entries.append(
                        FeedEntry(
                            content_type=paper_content_type,
                            object_id=paper.id,
                            parent_content_type=hub_content_type,
                            parent_object_id=hub.id,
                            action="PUBLISH",
                            action_date=paper.paper_publish_date,
                            user=paper.uploaded_by,
                        )
                    )
                    created_count += 1

        # Bulk create the feed entries
        if feed_entries:
            FeedEntry.objects.bulk_create(feed_entries)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully created {created_count} feed entries")
            )
        else:
            self.stdout.write(self.style.WARNING("No new feed entries were created"))
