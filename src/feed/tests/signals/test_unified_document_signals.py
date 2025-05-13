from django.test import TestCase, override_settings
from django.utils import timezone

from feed.models import FeedEntry
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper


class UnifiedDocumentSignalsTests(TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def setUp(self):
        self.hub = create_hub(name="Test Hub")
        self.paper = create_paper(title="Test Paper")
        self.paper.paper_publish_date = timezone.now()
        self.paper.save()

        # Add to hub to create feed entries
        self.paper.unified_document.hubs.add(self.hub)

        # Verify feed entries exist
        self.feed_entries = FeedEntry.objects.filter(
            unified_document=self.paper.unified_document
        )
        self.assertTrue(
            self.feed_entries.exists(), "Feed entries should be created for the paper"
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_deleted_when_unified_document_is_removed(self):
        """Test feed entries deletion when unified document is marked as removed."""
        # Get the unified document
        unified_document = self.paper.unified_document

        # Verify feed entries exist before removal
        initial_count = FeedEntry.objects.filter(
            unified_document=unified_document
        ).count()
        self.assertGreater(initial_count, 0, "Feed entries should exist before removal")

        # Mark the unified document as removed
        unified_document.is_removed = True
        unified_document.save()

        # Verify feed entries are deleted
        final_count = FeedEntry.objects.filter(
            unified_document=unified_document
        ).count()
        self.assertEqual(final_count, 0, "Feed entries should be deleted after removal")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_not_deleted_when_non_removal_update_occurs(self):
        """Test that feed entries are not deleted when unified document is updated."""
        # Get the unified document
        unified_document = self.paper.unified_document

        # Verify feed entries exist before update
        initial_count = FeedEntry.objects.filter(
            unified_document=unified_document
        ).count()
        self.assertGreater(initial_count, 0, "Feed entries should exist before update")

        # Update the unified document without removing it
        unified_document.score = 100  # Update some other field
        unified_document.save()

        # Verify feed entries still exist
        final_count = FeedEntry.objects.filter(
            unified_document=unified_document
        ).count()
        self.assertEqual(
            final_count,
            initial_count,
            "Feed entries should not be deleted after non-removal update",
        )
