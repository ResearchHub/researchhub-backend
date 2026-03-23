from django.contrib.contenttypes.models import ContentType
from django.test import override_settings
from django.utils import timezone

from feed.models import FeedEntry
from feed.serializers import serialize_feed_item
from feed.tasks import create_feed_entry
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import PEER_REVIEW
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from review.models.review_model import Review
from user.models import User
from utils.test_helpers import AWSMockTestCase


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class ReviewSignalsTests(AWSMockTestCase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(username="reviewer")
        self.paper = Paper.objects.create(title="Test Paper")
        self.unified_document = self.paper.unified_document

        paper_ct = ContentType.objects.get_for_model(Paper)
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=paper_ct,
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "review comment"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=self.thread,
        )

        # Create the comment's feed entry (with review: null in cached content)
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        self.comment_entry = create_feed_entry(
            item_id=self.comment.id,
            item_content_type_id=comment_ct.id,
            action=FeedEntry.PUBLISH,
            user_id=self.user.id,
        )

    def test_comment_feed_entry_includes_review_after_review_created(self):
        """
        Creating a review should refresh the comment's feed entry so its content
        includes the review score.
        """
        # Arrange
        self.assertIsNone(self.comment_entry.content.get("review"))
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        # Act
        Review.objects.create(
            score=4.0,
            created_by=self.user,
            content_type=comment_ct,
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Assert
        self.comment_entry.refresh_from_db()
        review_data = self.comment_entry.content.get("review")
        self.assertIsNotNone(review_data)
        self.assertEqual(review_data["score"], 4.0)

    def test_document_feed_entry_updates_reviews_after_review_created(self):
        """
        Creating a review should refresh the document's feed entry so document-level
        review data stays current.
        """
        # Arrange
        paper_ct = ContentType.objects.get_for_model(Paper)
        document_entry = FeedEntry.objects.create(
            content_type=paper_ct,
            object_id=self.paper.id,
            unified_document=self.unified_document,
            user=self.user,
            action=FeedEntry.PUBLISH,
            action_date=timezone.now(),
            content=serialize_feed_item(self.paper, paper_ct),
            metrics={},
        )
        self.assertEqual(document_entry.content.get("reviews"), [])
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        # Act
        Review.objects.create(
            score=4.0,
            created_by=self.user,
            content_type=comment_ct,
            object_id=self.comment.id,
            unified_document=self.unified_document,
        )

        # Assert
        document_entry.refresh_from_db()
        reviews = document_entry.content.get("reviews")
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]["score"], 4.0)

    def test_review_without_unified_document_does_not_refresh(self):
        """
        Reviews without a unified document should not update any feed entries.
        """
        # Arrange
        original_content = dict(self.comment_entry.content)
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)

        # Act
        Review.objects.create(
            score=3.0,
            created_by=self.user,
            content_type=comment_ct,
            object_id=self.comment.id,
            unified_document=None,
        )

        # Assert
        self.comment_entry.refresh_from_db()
        self.assertEqual(self.comment_entry.content, original_content)
