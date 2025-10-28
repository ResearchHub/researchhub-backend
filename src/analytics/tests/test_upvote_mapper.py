from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.constants.event_types import UPVOTE
from analytics.interactions import map_from_upvote
from analytics.models import UserInteractions
from discussion.models import Vote
from researchhub_document.helpers import create_post

User = get_user_model()


class UpvoteInteractionMapperTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="test@researchhub.com",
            first_name="Test",
            last_name="User",
        )
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

    def test_map_from_upvote_returns_correct_instance(self):
        """Test that map_from_upvote correctly maps a Vote to UserInteractions."""
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        interaction = map_from_upvote(vote)

        self.assertIsInstance(interaction, UserInteractions)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, UPVOTE)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, vote.content_type)
        self.assertEqual(interaction.object_id, vote.object_id)
        self.assertEqual(interaction.event_timestamp, vote.created_date)
        self.assertFalse(interaction.is_synced_with_personalize)
        self.assertIsNone(interaction.personalize_rec_id)

    def test_map_from_upvote_not_saved_to_database(self):
        """Test that map_from_upvote returns an unsaved instance."""
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        initial_count = UserInteractions.objects.count()
        interaction = map_from_upvote(vote)
        after_map_count = UserInteractions.objects.count()

        # Verify the instance is not saved yet
        self.assertEqual(initial_count, after_map_count)
        self.assertIsNone(interaction.id)

        # Verify it can be saved
        interaction.save()
        self.assertIsNotNone(interaction.id)
        self.assertEqual(UserInteractions.objects.count(), initial_count + 1)
