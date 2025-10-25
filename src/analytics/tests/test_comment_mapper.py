"""
Unit tests for Comment mapper.

Tests the mapping of RhCommentModel records to Personalize interactions,
including critical tests for bounty comment exclusion.
"""

from datetime import timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone as django_timezone

from analytics.services.personalize_constants import COMMENT_CREATED, EVENT_WEIGHTS
from analytics.services.personalize_mappers.comment_mapper import CommentMapper
from analytics.services.personalize_utils import datetime_to_epoch_seconds
from paper.models import Paper
from reputation.related_models.bounty import Bounty
from reputation.related_models.escrow import Escrow
from researchhub_comment.constants.rh_comment_thread_types import (
    ANSWER,
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.models import User


class TestCommentMapper(TestCase):
    """Tests for CommentMapper class."""

    def setUp(self):
        self.user = User.objects.create(username="testuser", email="test@example.com")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="PAPER"
        )
        self.paper = Paper.objects.create(
            title="Test Paper",
            unified_document=self.unified_doc,
            uploaded_by=self.user,
        )

        # Create comment thread
        self.thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            thread_type=GENERIC_COMMENT,
            created_by=self.user,
        )

    def test_event_type_name(self):
        """Test event type name property."""
        mapper = CommentMapper()
        self.assertEqual(mapper.event_type_name, "comment")

    def test_get_queryset_only_generic_comments(self):
        """Test that queryset includes only GENERIC_COMMENT type."""
        # Create GENERIC_COMMENT
        generic_comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Generic comment"}]},
        )

        # Create ANSWER type comment (should be excluded)
        RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=ANSWER,
            comment_content_json={"ops": [{"insert": "Answer comment"}]},
        )

        # Create PEER_REVIEW type comment (should be excluded)
        RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=PEER_REVIEW,
            comment_content_json={"ops": [{"insert": "Review comment"}]},
        )

        mapper = CommentMapper()
        queryset = mapper.get_queryset()

        # Should only return GENERIC_COMMENT
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, generic_comment.id)
        self.assertEqual(queryset.first().comment_type, GENERIC_COMMENT)

    def test_get_queryset_excludes_bounty_comments(self):
        """Test that comments with bounties attached are excluded (CRITICAL TEST)."""
        # Create comment without bounty
        comment_without_bounty = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Regular comment"}]},
        )

        # Create comment with bounty
        comment_with_bounty = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Comment with bounty"}]},
        )

        # Attach bounty to comment - create escrow first
        bounty_ct = ContentType.objects.get_for_model(Bounty)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            content_type=bounty_ct,
            object_id=1,  # Temporary
        )

        bounty = Bounty.objects.create(
            created_by=self.user,
            unified_document=self.unified_doc,
            item_content_type=ContentType.objects.get_for_model(RhCommentModel),
            item_object_id=comment_with_bounty.id,
            amount=100,
            escrow=escrow,
        )

        escrow.object_id = bounty.id
        escrow.save()

        mapper = CommentMapper()
        queryset = mapper.get_queryset()

        # Should only return comment without bounty
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, comment_without_bounty.id)
        # Verify the comment with bounty is NOT in the queryset
        self.assertNotIn(comment_with_bounty.id, queryset.values_list("id", flat=True))

    def test_get_queryset_with_date_filters(self):
        """Test queryset filtering by date range."""
        now = django_timezone.now()
        past_date = now - timedelta(days=10)

        # Create comment in the past
        past_comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Past comment"}]},
        )
        past_comment.created_date = past_date
        past_comment.save()

        # Create comment now
        current_comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Current comment"}]},
        )

        mapper = CommentMapper()

        # Filter by start date
        queryset = mapper.get_queryset(start_date=now - timedelta(days=1))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, current_comment.id)

        # Filter by end date
        queryset = mapper.get_queryset(end_date=now - timedelta(days=5))
        self.assertEqual(queryset.count(), 1)
        self.assertEqual(queryset.first().id, past_comment.id)

        # Filter by date range
        queryset = mapper.get_queryset(
            start_date=past_date - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )
        self.assertEqual(queryset.count(), 2)

    def test_map_comment_to_interaction(self):
        """Test mapping a comment to COMMENT_CREATED interaction."""
        comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        mapper = CommentMapper()
        interactions = mapper.map_to_interactions(comment)

        # Should create exactly one interaction
        self.assertEqual(len(interactions), 1)

        interaction = interactions[0]
        self.assertEqual(interaction["USER_ID"], str(self.user.id))
        self.assertEqual(interaction["ITEM_ID"], str(self.unified_doc.id))
        self.assertEqual(interaction["EVENT_TYPE"], COMMENT_CREATED)
        self.assertEqual(interaction["EVENT_VALUE"], EVENT_WEIGHTS[COMMENT_CREATED])
        self.assertIsNone(interaction["DEVICE"])
        self.assertIsNone(interaction["IMPRESSION"])
        self.assertIsNone(interaction["RECOMMENDATION_ID"])
        self.assertEqual(
            interaction["TIMESTAMP"],
            datetime_to_epoch_seconds(comment.created_date),
        )

    def test_timestamp_is_integer(self):
        """Test that timestamp is converted to integer epoch seconds."""
        comment = RhCommentModel.objects.create(
            thread=self.thread,
            created_by=self.user,
            comment_type=GENERIC_COMMENT,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )

        mapper = CommentMapper()
        interactions = mapper.map_to_interactions(comment)

        timestamp = interactions[0]["TIMESTAMP"]
        self.assertIsInstance(timestamp, int)
        # Timestamp should be reasonable (after 2020)
        self.assertGreater(timestamp, 1577836800)  # Jan 1, 2020
