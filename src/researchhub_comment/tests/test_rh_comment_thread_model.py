from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from paper.models import Paper  # Assuming Paper is a valid target content model
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
    SUMMARY,
)
from researchhub_comment.models import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)

User = get_user_model()


class TestRhCommentThreadModel(TestCase):
    def setUp(self):
        # Create a test user
        self.user = User.objects.create_user(username="testuser", password="12345")

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
        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates()

        self.assertEqual(aggregates["discussion_count"], 0)
        self.assertEqual(aggregates["review_count"], 0)
        self.assertEqual(aggregates["summary_count"], 0)

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

        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates()

        self.assertEqual(
            aggregates["discussion_count"], 6
        )  # All comments count towards discussion
        self.assertEqual(
            aggregates["review_count"], 1
        )  # Only the reply in review thread
        self.assertEqual(
            aggregates["summary_count"], 1
        )  # Only the reply in summary thread

    def test_get_discussion_aggregates_with_removed_comments(self):
        """Test aggregates when some comments are removed"""
        # Create parent comments
        generic_parent = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic parent comment"}]},
            created_by=self.user,
        )
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Review parent comment"}]},
            created_by=self.user,
        )

        # Create removed reply, should not be counted
        removed_comment = RhCommentModel.objects.create(
            thread=self.generic_thread,
            comment_content_json={"ops": [{"insert": "Generic reply"}]},
            parent=generic_parent,
            is_removed=True,
            created_by=self.user,
        )
        # Child of removed comment should not be counted
        RhCommentModel.objects.create(
            thread=self.review_thread,
            comment_content_json={"ops": [{"insert": "Review reply"}]},
            parent=removed_comment,
            created_by=self.user,
        )

        aggregates = RhCommentThreadModel.objects.get_discussion_aggregates()

        self.assertEqual(aggregates["discussion_count"], 2)
        self.assertEqual(aggregates["review_count"], 1)
        self.assertEqual(aggregates["summary_count"], 0)
