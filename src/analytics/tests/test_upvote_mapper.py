from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from analytics.constants.event_types import UPVOTE
from analytics.interactions import UpvoteInteractionMapper
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
        self.mapper = UpvoteInteractionMapper()

    def test_upvote_interaction_mapper_filters_by_date_range(self):
        now = timezone.now()
        two_days_ago = now - timedelta(days=2)
        yesterday = now - timedelta(days=1)

        post2 = create_post(created_by=self.user)
        post3 = create_post(created_by=self.user)

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

        queryset = self.mapper.get_queryset(
            start_date=yesterday - timedelta(hours=1),
            end_date=yesterday + timedelta(hours=1),
        )

        self.assertEqual(queryset.count(), 1)
        self.assertIn(old_vote, queryset)
        self.assertNotIn(very_old_vote, queryset)
        self.assertNotIn(recent_vote, queryset)

    def test_upvote_interaction_mapper_returns_instance(self):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        interaction = self.mapper.map_to_interaction(vote)

        self.assertIsInstance(interaction, UserInteractions)
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, UPVOTE)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, vote.content_type)
        self.assertEqual(interaction.object_id, vote.object_id)
        self.assertEqual(interaction.event_timestamp, vote.created_date)
        self.assertFalse(interaction.is_synced_with_personalize)
        self.assertIsNone(interaction.personalize_rec_id)

    def test_only_upvotes_excluded_downvotes(self):
        post2 = create_post(created_by=self.user)
        post3 = create_post(created_by=self.user)

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

        queryset = self.mapper.get_queryset()

        self.assertEqual(queryset.count(), 1)
        self.assertIn(upvote, queryset)
        self.assertNotIn(downvote, queryset)
        self.assertNotIn(neutral, queryset)

    def test_queryset_without_dates(self):
        vote1 = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        post2 = create_post(created_by=self.user)
        content_type2 = ContentType.objects.get_for_model(post2)
        vote2 = Vote.objects.create(
            created_by=self.user,
            content_type=content_type2,
            object_id=post2.id,
            vote_type=Vote.UPVOTE,
        )

        queryset = self.mapper.get_queryset()

        self.assertEqual(queryset.count(), 2)
        self.assertIn(vote1, queryset)
        self.assertIn(vote2, queryset)
