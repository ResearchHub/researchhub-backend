from django.core.management.base import BaseCommand

from feed.models import FeedEntry
from feed.tasks import serialize_feed_item

CHUNK_SIZE = 1000


class Command(BaseCommand):

    def handle(self, *args, **options):
        for feed_entry in FeedEntry.objects.filter(content={}).iterator(
            chunk_size=CHUNK_SIZE
        ):
            feed_item = feed_entry.item
            content = serialize_feed_item(feed_item, feed_entry.content_type)
            print(f"Saving content for feed_entry: {feed_entry.id}")
            feed_entry.content = content
            feed_entry.save(update_fields=["content"])
