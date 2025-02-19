from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.tasks import create_feed_entry, delete_feed_entry
from hub.models import Hub
from paper.models import Paper
from user.models import User


class FeedTasksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(username="testUser1")

        self.paper = Paper.objects.create(
            title="testPaper1", paper_publish_date="2025-01-01"
        )
        self.hub = Hub.objects.create(name="testHub1")

        self.paper_content_type = ContentType.objects.get_for_model(Paper)
        self.hub_content_type = ContentType.objects.get_for_model(Hub)

    def test_create_feed_entry(self):
        """Test creating a feed entry for a paper"""
        # Act
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            parent_item_id=self.hub.id,
            parent_content_type_id=self.hub_content_type.id,
            user_id=self.user.id,
        )

        # Assert
        feed_entry = FeedEntry.objects.get(
            object_id=self.paper.id, content_type=self.paper_content_type
        )

        self.assertEqual(feed_entry.user, self.user)
        self.assertEqual(feed_entry.action, FeedEntry.PUBLISH)
        self.assertEqual(feed_entry.item, self.paper)
        self.assertEqual(feed_entry.parent_item, self.hub)

    def test_create_feed_entry_twice(self):
        """Test that attempting to create the same feed entry twice doesn't raise an error"""
        # Act
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            parent_item_id=self.hub.id,
            parent_content_type_id=self.hub_content_type.id,
        )
        # attempt to create the same feed entry again
        create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            parent_item_id=self.hub.id,
            parent_content_type_id=self.hub_content_type.id,
        )

        # Assert
        feed_entries = FeedEntry.objects.filter(
            id=feed_entry.id
        )
        self.assertEqual(feed_entries.count(), 1)

    def test_delete_feed_entry(self):
        """Test deleting a feed entry for a paper"""
        # Arrange
        feed_entry = create_feed_entry(
            item_id=self.paper.id,
            item_content_type_id=self.paper_content_type.id,
            action=FeedEntry.PUBLISH,
            parent_item_id=self.hub.id,
            parent_content_type_id=self.hub_content_type.id,
            user_id=self.user.id,
        )

        # Act
        delete_feed_entry(
            item_id=feed_entry.item.id,
            item_content_type_id=feed_entry.content_type.id,
            parent_item_id=feed_entry.parent_item.id,
            parent_item_content_type_id=feed_entry.parent_content_type.id,
        )

        # Assert
        self.assertFalse(FeedEntry.objects.filter(id=feed_entry.id).exists())
