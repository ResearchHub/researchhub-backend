from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from discussion.models import Comment, Thread
from feed.models import FeedEntry
from purchase.related_models.purchase_model import Purchase
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_user


class TestPurchaseSignals(TestCase):
    def setUp(self):
        self.user = create_user("test@example.com", "password")

        # Create a unified document
        self.unified_document = ResearchhubUnifiedDocument.objects.create()

        # Create a post connected to the unified document
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=self.unified_document,
            created_by=self.user,
        )

        # Create a feed entry for the post
        self.post_content_type = ContentType.objects.get_for_model(self.post)
        self.feed_entry = FeedEntry.objects.create(
            content_type=self.post_content_type,
            object_id=self.post.id,
            action="PUBLISH",
            action_date=self.post.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_refresh_feed_entries_on_purchase_create(
        self,
    ):
        """Test that feed entries are refreshed when a purchase is created"""

        # Initial check - feed entry content should be empty
        self.assertEqual(self.feed_entry.content, {})
        self.assertEqual(self.feed_entry.metrics, {})

        # Create a purchase for the post
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Refresh the feed entry from the database
        self.feed_entry.refresh_from_db()

        # The feed entry should now have content and metrics
        self.assertNotEqual(self.feed_entry.content, {})
        self.assertIsInstance(self.feed_entry.content, dict)

        # Verify the purchase data is included in the feed entry content
        purchase_data = []
        if "purchases" in self.feed_entry.content:
            purchase_data = self.feed_entry.content["purchases"]

        self.assertTrue(isinstance(purchase_data, list))
        self.assertEqual(len(purchase_data), 1)
        self.assertEqual(float(purchase_data[0]["amount"]), float(purchase.amount))

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_refresh_feed_entries_on_purchase_update(
        self,
    ):
        """Test that feed entries are refreshed when a purchase is updated"""

        # Create a purchase for the post
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Refresh the feed entry and clear content
        self.feed_entry.refresh_from_db()
        self.feed_entry.content = {}
        self.feed_entry.save()

        # Update the purchase
        purchase.amount = "20.0"
        purchase.save()

        # Refresh feed entry from database
        self.feed_entry.refresh_from_db()

        # The feed entry should have content again
        self.assertNotEqual(self.feed_entry.content, {})

        # Verify the updated purchase data is included in the feed entry content
        purchase_data = []
        if "purchases" in self.feed_entry.content:
            purchase_data = self.feed_entry.content["purchases"]

        self.assertTrue(isinstance(purchase_data, list))
        self.assertEqual(len(purchase_data), 1)
        self.assertEqual(float(purchase_data[0]["amount"]), 20.0)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def test_refresh_feed_entries_on_comment_purchase(
        self,
    ):
        """Test that feed entries are refreshed when a purchase is made on a comment"""

        # Create a thread for the post
        thread = Thread.objects.create(
            title="Test Thread",
            post=self.post,
            created_by=self.user,
            unified_document=self.unified_document,
        )

        # Create a comment on the thread
        comment = Comment.objects.create(
            parent=thread,
            created_by=self.user,
            plain_text="Test Comment",
        )

        # Create a feed entry for the comment
        comment_content_type = ContentType.objects.get_for_model(comment)
        comment_feed_entry = FeedEntry.objects.create(
            content_type=comment_content_type,
            object_id=comment.id,
            action="PUBLISH",
            action_date=comment.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

        # Initial check - feed entries content should be empty
        self.assertEqual(self.feed_entry.content, {})
        self.assertEqual(comment_feed_entry.content, {})

        # Create a purchase for the comment
        purchase = Purchase.objects.create(
            user=self.user,
            content_type=comment_content_type,
            object_id=comment.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="15.0",
        )

        # Refresh both feed entries from the database
        self.feed_entry.refresh_from_db()
        comment_feed_entry.refresh_from_db()

        # The comment feed entry should now have content and metrics
        self.assertNotEqual(comment_feed_entry.content, {})

        # Verify the purchase data is included in the comment feed entry content
        comment_purchase_data = []
        if "purchases" in comment_feed_entry.content:
            comment_purchase_data = comment_feed_entry.content["purchases"]

        self.assertTrue(isinstance(comment_purchase_data, list))
        self.assertEqual(len(comment_purchase_data), 1)

        purchase_amount = float(purchase.amount)
        comment_amount = float(comment_purchase_data[0]["amount"])
        self.assertEqual(comment_amount, purchase_amount)

        # Post feed entry should also be updated (shared unified document)
        self.assertNotEqual(self.feed_entry.content, {})
        purchase_data = []
        if "purchases" in self.feed_entry.content:
            purchase_data = self.feed_entry.content["purchases"]

        self.assertTrue(isinstance(purchase_data, list))
        self.assertEqual(len(purchase_data), 1)
        self.assertEqual(float(purchase_data[0]["amount"]), float(purchase.amount))
