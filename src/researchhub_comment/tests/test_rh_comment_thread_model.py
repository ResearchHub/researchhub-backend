import uuid

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.models import Paper  # Assuming Paper is a valid target content model
from reputation.models import Bounty, Escrow
from researchhub_comment.constants.rh_comment_thread_types import (
    COMMUNITY_REVIEW,
    GENERIC_COMMENT,
    PEER_REVIEW,
    SUMMARY,
)
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.models import ResearchhubUnifiedDocument

User = get_user_model()


class TestRhCommentThreadModel(TestCase):
    def setUp(self):
        # Create a test user
        self.user = User.objects.create_user(
            username="testuser", password=uuid.uuid4().hex
        )

        # Create a paper to attach threads to
        self.paper = Paper.objects.create(title="Test Paper")
        self.content_type = ContentType.objects.get_for_model(self.paper)

        # Create different types of threads
        self.generic_thread = RhCommentThreadModel.objects.create(
            thread_type=GENERIC_COMMENT,
            content_type=self.content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.review_thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=self.content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.summary_thread = RhCommentThreadModel.objects.create(
            thread_type=SUMMARY,
            content_type=self.content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )

    def test_get_discussion_aggregates_empty(self):
        """Test aggregates when there are no comments"""
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        self.assertEqual(aggregates["discussion_count"], 0)
        self.assertEqual(aggregates["review_count"], 0)

    def test_get_discussion_aggregates_with_comments(self):
        """Test aggregates with various comment types"""
        # Create parent comments
        generic_parent = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic parent comment"}]},
            created_by=self.user,
        )
        review_parent = RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Review parent comment"}]},
            created_by=self.user,
        )
        summary_parent = RhCommentModel.objects.create(
            thread=self.summary_thread,
            comment_content_json={"ops": [{"insert": "Summary parent comment"}]},
            created_by=self.user,
        )

        # Create replies
        RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic reply"}]},
            parent=generic_parent,
            created_by=self.user,
        )
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Review reply"}]},
            parent=review_parent,
            created_by=self.user,
        )
        RhCommentModel.objects.create(
            thread=self.summary_thread,
            comment_content_json={"ops": [{"insert": "Summary reply"}]},
            parent=summary_parent,
            created_by=self.user,
        )

        generic_parent.refresh_related_discussion_count()
        self.paper.refresh_from_db()

        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        self.assertEqual(
            aggregates["discussion_count"], 6
        )  # All comments count towards discussion
        self.assertEqual(
            aggregates["review_count"], 0
        )  # Only the reply in review thread

    def test_get_discussion_aggregates_with_bounty_count(self):
        """Test that bounty_count correctly counts comments with bounties"""
        # Create unified document for bounty
        unified_document = ResearchhubUnifiedDocument.objects.create()
        self.paper.unified_document = unified_document
        self.paper.save()

        # Create escrow for bounty (using Paper as the item)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=500,
            object_id=self.paper.id,
            content_type=self.content_type,
        )

        # Create top-level comments
        comment1 = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Comment with bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
        )
        comment2 = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Another comment with bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
        )
        comment3 = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Comment without bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
        )

        # Create nested comment with bounty (should NOT be counted)
        nested_comment = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Nested comment with bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            parent=comment1,  # This is nested under comment1
        )

        # Create bounties for first two top-level comments
        Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=comment1,
            unified_document=unified_document,
            amount=100,
        )
        Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=comment2,
            unified_document=unified_document,
            amount=200,
        )

        # Create bounty for nested comment (should NOT be counted)
        Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=nested_comment,
            unified_document=unified_document,
            amount=150,
        )

        # Refresh discussion count to update the stored value
        comment1.refresh_related_discussion_count()
        self.paper.refresh_from_db()

        # Get aggregates
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        # Assert bounty_count is 2 (only top-level comments with bounties)
        self.assertEqual(aggregates["bounty_count"], 2)
        # Assert conversation_count now uses discussion_count (only non-bounty GENERIC_COMMENT)
        # comment1 and comment2 have bounties, comment3 doesn't, nested_comment has bounty
        # So only comment3 and its non-bounty children count = 1
        self.assertEqual(aggregates["conversation_count"], 1)

    def test_get_discussion_aggregates_conversation_count(self):
        """Test conversation_count correctly counts generic comments without bounties"""
        # Create various comment types (top-level)
        generic1 = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic comment 1"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
        )
        generic2 = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic comment 2"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
        )
        # Create nested generic comments (should NOT be counted in conversation_count)
        RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Nested reply to generic 1"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            parent=generic1,  # This is nested
        )
        RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Nested reply to generic 2"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            parent=generic2,  # This is nested
        )

        # Create a peer review comment (should not be counted as conversation)
        peer_review = RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Peer review comment"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
        )
        # Create a community review comment (should not be counted as conversation)
        community_review = RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Community review comment"}]},
            comment_type=COMMUNITY_REVIEW,
            created_by=self.user,
        )
        # Create nested review comments (should NOT be counted in review_count)
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Reply to peer review"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            parent=peer_review,  # This is nested
        )
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Reply to community review"}]},
            comment_type=COMMUNITY_REVIEW,
            created_by=self.user,
            parent=community_review,  # This is nested
        )

        # Refresh discussion count to update the stored value
        generic1.refresh_related_discussion_count()
        self.paper.refresh_from_db()

        # Get aggregates
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        # Assert conversation_count now uses discussion_count (all GENERIC_COMMENT in generic threads)
        self.assertEqual(aggregates["conversation_count"], 4)
        # Assert review_count is 2 (only top-level review comments)
        self.assertEqual(aggregates["review_count"], 2)
        # Assert bounty_count is 0
        self.assertEqual(aggregates["bounty_count"], 0)

    def test_get_discussion_aggregates_removed_comments(self):
        """Test that removed comments are not counted in any aggregate"""
        # Create unified document for bounty
        unified_document = ResearchhubUnifiedDocument.objects.create()
        self.paper.unified_document = unified_document
        self.paper.save()

        # Create escrow for bounty (using Paper as the item)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=300,
            object_id=self.paper.id,
            content_type=self.content_type,
        )

        # Create comments - some removed
        comment_with_bounty = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Comment with bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            is_removed=False,
        )
        removed_comment_with_bounty = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Removed comment with bounty"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            is_removed=True,
        )
        RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            is_removed=False,
        )
        RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Removed generic comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            is_removed=True,
        )
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Review comment"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            is_removed=False,
        )
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Removed review comment"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            is_removed=True,
        )

        # Create bounties
        Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=comment_with_bounty,
            unified_document=unified_document,
            amount=100,
        )
        Bounty.objects.create(
            created_by=self.user,
            escrow=escrow,
            item=removed_comment_with_bounty,
            unified_document=unified_document,
            amount=200,
        )

        # Refresh discussion count to update the stored value
        comment_with_bounty.refresh_related_discussion_count()
        self.paper.refresh_from_db()

        # Get aggregates
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        # Assert only non-removed comments are counted
        self.assertEqual(
            aggregates["bounty_count"], 1
        )  # Only non-removed bounty comment
        # conversation_count uses discussion_count which excludes bounty comments
        # comment_with_bounty has bounty (excluded), removed_comment_with_bounty (excluded),
        # 1 generic without bounty (counted), 1 removed generic (excluded)
        self.assertEqual(
            aggregates["conversation_count"], 1
        )  # Only non-removed, non-bounty GENERIC_COMMENT
        self.assertEqual(
            aggregates["review_count"], 1
        )  # Only non-removed review comment

    def test_get_discussion_aggregates_mixed_scenario(self):
        """Test aggregates with a mix of comments, bounties, and reviews"""
        # Create unified document for bounty
        unified_document = ResearchhubUnifiedDocument.objects.create()
        self.paper.unified_document = unified_document
        self.paper.save()

        # Create escrow for bounty (using Paper as the item)
        escrow = Escrow.objects.create(
            created_by=self.user,
            hold_type=Escrow.BOUNTY,
            amount_holding=1000,
            object_id=self.paper.id,
            content_type=self.content_type,
        )

        # Create various comments
        # Generic comments with bounties
        for i in range(3):
            comment = RhCommentModel.objects.create(
                thread=self.generic_thread,
                comment_content_json={"ops": [{"insert": f"Bounty comment {i}"}]},
                comment_type=GENERIC_COMMENT,
                created_by=self.user,
            )
            Bounty.objects.create(
                created_by=self.user,
                escrow=escrow,
                item=comment,
                unified_document=unified_document,
                amount=100 * (i + 1),
            )

        # Generic comments without bounties
        for i in range(5):
            RhCommentModel.objects.create(
                thread=self.generic_thread,
                comment_content_json={"ops": [{"insert": f"Generic comment {i}"}]},
                comment_type=GENERIC_COMMENT,
                created_by=self.user,
            )

        # Review comments (no bounties on these)
        for i in range(2):
            RhCommentModel.objects.create(
                thread=self.review_thread,
                comment_content_json={"ops": [{"insert": f"Peer review {i}"}]},
                comment_type=PEER_REVIEW,
                created_by=self.user,
            )

        for i in range(3):
            RhCommentModel.objects.create(
                thread=self.review_thread,
                comment_content_json={"ops": [{"insert": f"Community review {i}"}]},
                comment_type=COMMUNITY_REVIEW,
                created_by=self.user,
            )

        # Refresh discussion count to update the stored value
        # Get the first comment to refresh from
        first_comment = RhCommentModel.objects.filter(
            thread=self.generic_thread
        ).first()
        if first_comment:
            first_comment.refresh_related_discussion_count()
        self.paper.refresh_from_db()

        # Get aggregates
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates(self.paper)

        # Assert counts
        self.assertEqual(aggregates["bounty_count"], 3)  # 3 comments with bounties
        # conversation_count uses discussion_count which excludes bounty comments
        # 3 comments have bounties (excluded), 5 generic comments without bounties (counted)
        self.assertEqual(
            aggregates["conversation_count"], 5
        )  # Only non-bounty GENERIC_COMMENT in generic thread
        self.assertEqual(aggregates["review_count"], 5)  # 2 peer + 3 community reviews
