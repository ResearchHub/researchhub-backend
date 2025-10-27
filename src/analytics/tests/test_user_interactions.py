from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import ITEM_UPVOTED, PAGE_VIEW
from analytics.models import UserInteractions
from researchhub_document.helpers import create_post

User = get_user_model()


class UserInteractionsModelTests(TestCase):
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@researchhub.com",
            first_name="Test",
            last_name="User",
        )

        # Create a post for unified document
        self.post = create_post(created_by=self.user)
        self.unified_document = self.post.unified_document

        # Get content type for the post
        self.content_type = ContentType.objects.get_for_model(self.post)

        self.event_timestamp = timezone.now()

    def test_unique_constraint_prevents_duplicate_interactions(self):
        """Test that unique constraint prevents duplicate user events on same item"""
        # Create first interaction
        UserInteractions.objects.create(
            user=self.user,
            event=ITEM_UPVOTED,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=self.event_timestamp,
        )

        # Attempt to create duplicate - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            UserInteractions.objects.create(
                user=self.user,
                event=ITEM_UPVOTED,
                unified_document=self.unified_document,
                content_type=self.content_type,
                object_id=self.post.id,
                event_timestamp=self.event_timestamp,
            )

    def test_same_user_can_have_different_events_on_same_document(self):
        """Test that same user can have multiple different event types on same item"""
        # Create upvote interaction
        upvote = UserInteractions.objects.create(
            user=self.user,
            event=ITEM_UPVOTED,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=self.event_timestamp,
        )

        # Create page view interaction on same item - should succeed
        page_view = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=self.event_timestamp,
        )

        self.assertIsNotNone(upvote.id)
        self.assertIsNotNone(page_view.id)
        self.assertNotEqual(upvote.id, page_view.id)

    def test_different_users_can_have_same_event_on_same_item(self):
        """Test that different users can have same event type on same item"""
        user2 = User.objects.create_user(
            username="testuser2", email="test2@researchhub.com"
        )

        # Create interaction for first user
        interaction1 = UserInteractions.objects.create(
            user=self.user,
            event=ITEM_UPVOTED,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=self.event_timestamp,
        )

        # Create same interaction for second user - should succeed
        interaction2 = UserInteractions.objects.create(
            user=user2,
            event=ITEM_UPVOTED,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=self.event_timestamp,
        )

        self.assertNotEqual(interaction1.id, interaction2.id)
