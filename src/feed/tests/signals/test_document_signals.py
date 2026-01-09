from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.utils import timezone

from feed.models import FeedEntry
from hub.tests.helpers import create_hub
from paper.tests.helpers import create_paper
from researchhub_document.helpers import create_post
from user.related_models.user_model import User
from utils.test_helpers import AWSMockTestCase, AWSMockTransactionTestCase


class DocumentSignalsTests(AWSMockTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="testUser1")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_created_when_hubs_are_added_to_paper(self):
        """
        Test that feed entries are created when hubs are added to a paper.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        paper = create_paper(title="testPaper1", uploaded_by=self.user)

        # Act
        paper.unified_document.hubs.add(hub1, hub2)
        paper.save()

        # Assert
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        )
        self.assertEqual(len(feed_entries), 1)
        self.assertEqual(feed_entries[0].hubs.count(), 2)
        self.assertEqual(feed_entries[0].user, paper.uploaded_by)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_deleted_when_all_hubs_are_removed_from_paper(self):
        """
        Test that feed entries are deleted when all hubs are removed from a paper.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        paper = create_paper(title="testPaper1", uploaded_by=self.user)
        paper.unified_document.hubs.add(hub1, hub2)
        paper.save()

        # Act
        paper.unified_document.hubs.remove(hub1, hub2)  # remove all hubs
        paper.save()

        # Assert
        feed_entries_exist = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        ).exists()
        self.assertFalse(feed_entries_exist)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_hubs_are_removed_from_feed_entries_when_all_hubs_are_removed_from_paper(
        self,
    ):
        """
        Test that hubs are removed from feed entries when all hubs are removed from a
        paper.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        paper = create_paper(title="testPaper1", uploaded_by=self.user)
        paper.unified_document.hubs.add(hub1, hub2)
        paper.save()

        # Act
        paper.unified_document.hubs.remove(hub1)  # remove one hub
        paper.save()

        # Assert
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        )
        self.assertEqual(len(feed_entries), 1)
        self.assertEqual(feed_entries[0].hubs.count(), 1)
        self.assertEqual(feed_entries[0].hubs.all()[0], hub2)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_created_when_papers_are_added_to_hubs(self):
        """
        Test that feed entries are created when papers are added to hubs.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        paper = create_paper(title="testPaper1", uploaded_by=self.user)
        paper.hubs.add(hub2)

        # Act
        hub1.related_documents.add(paper.unified_document)
        hub1.save()

        # Assert
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(paper),
            object_id=paper.id,
        )
        self.assertEqual(len(feed_entries), 1)
        self.assertEqual(feed_entries.first().hubs.count(), 2)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_created_when_hubs_are_added_to_post(self):
        """
        Test that feed entries are created when posts are added to hubs.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        post = create_post(title="testPaper1", created_by=self.user)

        # Act
        post.unified_document.hubs.add(hub1, hub2)
        post.save()

        # Assert
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
        )
        self.assertEqual(len(feed_entries), 1)
        self.assertEqual(feed_entries[0].hubs.count(), 2)
        self.assertEqual(feed_entries[0].user, post.created_by)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_feed_entries_are_deleted_when_all_hubs_are_removed_from_post(self):
        """
        Test that feed entries are deleted when all hubs are removed from a post.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        post = create_post(title="testPaper1", created_by=self.user)

        # Act
        post.unified_document.hubs.remove(hub1, hub2)  # remove all hubs
        post.save()

        # Assert
        feed_entries_exist = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
        ).exists()

        self.assertFalse(feed_entries_exist)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_hubs_are_removed_from_feed_entries_when_all_hubs_are_removed_from_post(
        self,
    ):
        """
        Test that hubs are removed from feed entries when hubs are removed from posts.
        """
        # Arrange
        hub1 = create_hub(name="testHub1")
        hub2 = create_hub(name="testHub2")
        post = create_post(title="testPaper1", created_by=self.user)
        post.unified_document.hubs.add(hub1, hub2)

        # Act
        post.unified_document.hubs.remove(hub1)  # remove one hub
        post.save()

        # Assert
        feed_entries = FeedEntry.objects.filter(
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
        )

        self.assertEqual(len(feed_entries), 1)
        self.assertEqual(feed_entries[0].hubs.count(), 1)
        self.assertEqual(feed_entries[0].hubs.first(), hub2)


class DocumentRemovalSignalsTests(AWSMockTransactionTestCase):
    """
    Uses AWSMockTransactionTestCase to allow transaction.on_commit() callbacks to execute.
    This is necessary because TestCase wraps tests in an atomic transaction that
    never commits, preventing on_commit hooks from firing.
    """

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def setUp(self):
        super().setUp()
        self.hub = create_hub(name="Test Hub")
        self.user = User.objects.create_user(username="testUser1")
        self.paper = create_paper(title="Test Paper", uploaded_by=self.user)
        self.paper.paper_publish_date = timezone.now()
        self.paper.save()

        # Add to hub to create feed entries
        self.paper.unified_document.hubs.add(self.hub)

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
