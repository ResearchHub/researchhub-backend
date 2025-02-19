from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from feed.models import FeedEntry
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper


class PaperSignalsTests(TestCase):
    def setUp(self):
        self.hub = create_hub(name="Test Hub")
        self.paper = create_paper(title="Test Paper")
        self.paper.paper_publish_date = timezone.now()
        self.paper.save()
        self.paper.unified_document.hubs.add(self.hub)

    def test_feed_entries_are_created_when_hubs_are_added(self):
        """Test that feed entries are created when unified document hubs are added."""
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )
        self.assertEqual(len(feed_entries), self.paper.unified_document.hubs.count())

    def test_feed_entries_are_deleted_when_hubs_are_removed(self):
        """Test that feed entries are deleted when unified document hubs are removed."""
        initial_hub = self.paper.unified_document.hubs.first()
        self.paper.unified_document.hubs.remove(initial_hub)

        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(self.paper),
            object_id=self.paper.id,
        )
        self.assertEqual(len(feed_entries), self.paper.unified_document.hubs.count())
