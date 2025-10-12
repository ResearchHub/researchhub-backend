"""
Unit tests for Upvote mapper.

Tests the mapping of Vote records (vote_type=UPVOTE) to Personalize interactions,
including critical tests for comment upvotes using correct unified document.
"""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import EVENT_WEIGHTS, ITEM_UPVOTED
from analytics.services.personalize_mappers.upvote_mapper import UpvoteMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from discussion.models import Vote
from paper.models import Paper
from researchhub_comment.constants.rh_comment_thread_types import GENERIC_COMMENT
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.constants.document_type import DISCUSSION
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestUpvoteMapper(TestCase):
    """Tests for UpvoteMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = UpvoteMapper()
        self.assertEqual(mapper.event_type_name, "upvote")

    def test_get_queryset_only_upvotes(self):
        """Test that queryset includes only UPVOTE, excludes NEUTRAL/DOWNVOTE."""
        # Create paper for voting
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        # Create UPVOTE
        upvote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        # Create NEUTRAL vote (should be excluded)
        user2 = User.objects.create(username="user2", email="user2@example.com")
        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=user2,
            vote_type=Vote.NEUTRAL,
        )

        # Create DOWNVOTE (should be excluded)
        user3 = User.objects.create(username="user3", email="user3@example.com")
        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=user3,
            vote_type=Vote.DOWNVOTE,
        )

        mapper = UpvoteMapper()
        queryset = mapper.get_queryset()

        # Should only return UPVOTE
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, upvote.id)
        self.assertEqual(queryset.first().vote_type, Vote.UPVOTE)

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        # Create vote in the past
        past_vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )
        past_vote.created_date = past_date
        past_vote.save()

        # Create vote now
        user2 = User.objects.create(username="user2", email="user2@example.com")
        current_vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=user2,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_vote.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_vote.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_paper_upvote(self):
        """Test mapping a paper upvote to ITEM_UPVOTED interaction."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], ITEM_UPVOTED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[ITEM_UPVOTED])
        self.assertEqual(interaction["EVENT_VALUE"], 1.0)
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(vote.created_date),
        )

    def test_map_post_upvote(self):
        """Test mapping a post upvote to ITEM_UPVOTED interaction."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION
        )
        post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=unified_doc,
            created_by=self.user,
            document_type=DISCUSSION,
        )

        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], ITEM_UPVOTED)
        self.assertEqual(interaction["EVENT_VALUE"], 1.0)

    def test_map_comment_upvote(self):
        """
        Test mapping a comment upvote to ITEM_UPVOTED interaction.
        CRITICAL: Verify that comment upvotes use the correct unified document
        (from the thread's content_object, not the comment itself).
        """
        # Create paper with unified doc
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        # Create comment thread for paper
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            thread_type=GENERIC_COMMENT,
        )

        # Create comment
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        # Create upvote on comment
        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        # CRITICAL: Should use paper's unified doc, not comment's
        self.assertEqual(interaction["ITEM_ID"], str(unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], ITEM_UPVOTED)
        self.assertEqual(interaction["EVENT_VALUE"], 1.0)

    def test_map_upvote_without_creator(self):
        """Test that votes without creator are skipped."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=None,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should return empty list
        self.assertEqual(len(interactions), 0)

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020

    def test_excludes_paper_self_vote(self):
        """Test that users upvoting their own papers are excluded."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,  # Paper uploaded by self.user
        )

        # Self-vote: same user upvotes their own paper
        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,  # Same user
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should return empty list (self-vote excluded)
        self.assertEqual(len(interactions), 0)

    def test_excludes_post_self_vote(self):
        """Test that users upvoting their own posts are excluded."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION
        )
        post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=unified_doc,
            created_by=self.user,  # Post created by self.user
            document_type=DISCUSSION,
        )

        # Self-vote: same user upvotes their own post
        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=post.id,
            created_by=self.user,  # Same user
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should return empty list (self-vote excluded)
        self.assertEqual(len(interactions), 0)

    def test_excludes_comment_self_vote(self):
        """Test that users upvoting their own comments are excluded."""
        # Create paper with unified doc
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,
        )

        # Create comment thread for paper
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            thread_type=GENERIC_COMMENT,
        )

        # Create comment by self.user
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,  # Comment created by self.user
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        # Self-vote: same user upvotes their own comment
        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            created_by=self.user,  # Same user
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should return empty list (self-vote excluded)
        self.assertEqual(len(interactions), 0)

    def test_includes_other_user_vote(self):
        """Test that votes from other users ARE included."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=self.user,  # Paper uploaded by self.user
        )

        # Different user upvotes the paper
        other_user = User.objects.create(
            username="otheruser", email="other@example.com"
        )
        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=other_user,  # Different user
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        interactions = mapper.map_to_interactions(vote)

        # Should create interaction (vote from another user)
        self.assertEqual(len(interactions), 1)
        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(other_user.id))
        self.assertEqual(interaction["ITEM_ID"], str(unified_doc.id))

    def test_self_vote_detection_with_none_fields(self):
        """Test that self-vote detection handles None fields gracefully."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(document_type="PAPER")
        # Paper with no uploaded_by (None)
        paper = Paper.objects.create(
            title="Test Paper",
            unified_document=unified_doc,
            uploaded_by=None,  # No creator
        )

        vote = Vote.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=paper.id,
            created_by=self.user,
            vote_type=Vote.UPVOTE,
        )

        mapper = UpvoteMapper()
        # Should not crash, should treat as not a self-vote
        interactions = mapper.map_to_interactions(vote)

        # Should create interaction (can't determine creator, so not self-vote)
        self.assertEqual(len(interactions), 1)
