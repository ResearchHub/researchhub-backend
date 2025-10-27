from datetime import timedelta

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

    def test_non_repeatable_event_prevents_duplicates(self):
        """Test that ITEM_UPVOTED cannot be duplicated"""
        # Create first upvote
        UserInteractions.objects.create(
            user=self.user,
            event=ITEM_UPVOTED,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timezone.now(),
        )

        # Attempt to create duplicate upvote - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            UserInteractions.objects.create(
                user=self.user,
                event=ITEM_UPVOTED,
                unified_document=self.unified_document,
                content_type=self.content_type,
                object_id=self.post.id,
                event_timestamp=timezone.now(),
            )

    def test_repeatable_event_blocks_same_day_duplicate(self):
        """Test that PAGE_VIEW cannot be duplicated on the same day"""
        # Create page view at 10am
        today_10am = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        today_3pm = timezone.now().replace(hour=15, minute=0, second=0, microsecond=0)

        UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=today_10am,
        )

        # Attempt to create another page view same day - should raise IntegrityError
        with self.assertRaises(IntegrityError):
            UserInteractions.objects.create(
                user=self.user,
                event=PAGE_VIEW,
                unified_document=self.unified_document,
                content_type=self.content_type,
                object_id=self.post.id,
                event_timestamp=today_3pm,
            )

    def test_repeatable_event_allows_different_day(self):
        """Test that PAGE_VIEW can be created on different days"""
        today = timezone.now()
        tomorrow = today + timedelta(days=1)

        # Create page view today
        interaction1 = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=today,
        )

        # Create page view tomorrow - should succeed
        interaction2 = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=tomorrow,
        )

        self.assertNotEqual(interaction1.id, interaction2.id)

    def test_different_users_can_have_same_event_on_same_item(self):
        """Test that different users can PAGE_VIEW same item on same day"""
        user2 = User.objects.create_user(
            username="testuser2", email="test2@researchhub.com"
        )
        timestamp = timezone.now()

        # Create page view for first user
        interaction1 = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timestamp,
        )

        # Create page view for second user same day - should succeed
        interaction2 = UserInteractions.objects.create(
            user=user2,
            event=PAGE_VIEW,
            unified_document=self.unified_document,
            content_type=self.content_type,
            object_id=self.post.id,
            event_timestamp=timestamp,
        )

        self.assertNotEqual(interaction1.id, interaction2.id)
