from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import ITEM_UPVOTED
from analytics.interactions import UpvoteInteractionMapper
from analytics.models import UserInteractions
from discussion.models import Vote
from researchhub_document.helpers import create_post

User = get_user_model()


class UpvoteInteractionMapperTests(TestCase):
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@researchhub.com",
            first_name="Test",
            last_name="User",
        )

        # Create a post for testing
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

        # Create mapper instance
        self.mapper = UpvoteInteractionMapper()

    def test_get_queryset_returns_only_upvotes(self):
        """Test that get_queryset only returns upvote records"""
        # Create posts for voting
        post2 = create_post(created_by=self.user)
        post3 = create_post(created_by=self.user)

        # Create different vote types
        upvote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        downvote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=post2.id,
            vote_type=Vote.DOWNVOTE,
        )

        neutral = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=post3.id,
            vote_type=Vote.NEUTRAL,
        )

        # Get queryset
        queryset = self.mapper.get_queryset()

        # Should only include upvote
        self.assertEqual(queryset.count(), 1)
        self.assertIn(upvote, queryset)
        self.assertNotIn(downvote, queryset)
        self.assertNotIn(neutral, queryset)

    def test_get_queryset_filters_by_date_range(self):
        """Test that get_queryset filters by both start and end dates"""
        now = timezone.now()
        two_days_ago = now - timedelta(days=2)
        yesterday = now - timedelta(days=1)

        # Create posts for voting
        post2 = create_post(created_by=self.user)
        post3 = create_post(created_by=self.user)

        # Create votes at different times
        very_old_vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )
        very_old_vote.created_date = two_days_ago
        very_old_vote.save()

        content_type2 = ContentType.objects.get_for_model(post2)
        old_vote = Vote.objects.create(
            created_by=self.user,
            content_type=content_type2,
            object_id=post2.id,
            vote_type=Vote.UPVOTE,
        )
        old_vote.created_date = yesterday
        old_vote.save()

        content_type3 = ContentType.objects.get_for_model(post3)
        recent_vote = Vote.objects.create(
            created_by=self.user,
            content_type=content_type3,
            object_id=post3.id,
            vote_type=Vote.UPVOTE,
        )

        # Filter for yesterday only
        queryset = self.mapper.get_queryset(
            start_date=yesterday - timedelta(hours=1),
            end_date=yesterday + timedelta(hours=1),
        )

        # Should only include yesterday's vote
        self.assertEqual(queryset.count(), 1)
        self.assertIn(old_vote, queryset)
        self.assertNotIn(very_old_vote, queryset)
        self.assertNotIn(recent_vote, queryset)

    def test_map_to_interaction_creates_correct_instance(self):
        """Test that map_to_interaction creates UserInteractions with correct fields"""
        # Create a vote
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        # Map to interaction
        interaction = self.mapper.map_to_interaction(vote)

        # Verify it's a UserInteractions instance
        self.assertIsInstance(interaction, UserInteractions)

        # Verify fields are mapped correctly
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, ITEM_UPVOTED)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, vote.content_type)
        self.assertEqual(interaction.object_id, vote.object_id)
        self.assertEqual(interaction.event_timestamp, vote.created_date)
        self.assertFalse(interaction.is_synced_with_personalize)
        self.assertIsNone(interaction.personalize_rec_id)
