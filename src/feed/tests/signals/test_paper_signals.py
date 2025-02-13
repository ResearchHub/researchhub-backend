from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from rest_framework.test import APITestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.models import Paper


class PaperSignalTests(APITestCase):
    def setUp(self):
        # Create test hubs
        self.hub1 = Hub.objects.create(name="Hub 1")
        self.hub2 = Hub.objects.create(name="Hub 2")
        self.hub3 = Hub.objects.create(name="Hub 3")

        # Create test papers
        self.paper1 = Paper.objects.create(
            title="Test Paper 1",
            paper_title="Test Paper 1",
            paper_publish_date="2024-01-01",
            doi="10.1234/test1",
        )
        self.paper2 = Paper.objects.create(
            title="Test Paper 2",
            paper_title="Test Paper 2",
            paper_publish_date="2024-01-01",
            doi="10.1234/test2",
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_add_paper_to_feed(self):
        """Test that feed entries are created when paper hubs are modified."""
        # Add hubs to papers and verify feed entries are created
        self.paper1.hubs.add(self.hub1, self.hub2)
        self.paper2.hubs.add(self.hub2, self.hub3)

        for paper in [self.paper1, self.paper2]:
            content_type = ContentType.objects.get_for_model(Paper)
            feed_entries = FeedEntry.objects.filter(
                content_type=content_type, object_id=paper.id
            )
            self.assertEqual(len(feed_entries), paper.hubs.count())
            self.assertEqual(feed_entries.first().action, "PUBLISH")
            self.assertEqual(feed_entries.first().item, paper)

            # Test that feed entries are updated when hubs change
            initial_hub = paper.hubs.first()
            paper.hubs.remove(initial_hub)
            feed_entries = FeedEntry.objects.filter(
                content_type=content_type, object_id=paper.id
            )
            self.assertEqual(len(feed_entries), paper.hubs.count())
