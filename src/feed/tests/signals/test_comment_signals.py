from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from hub.models import Hub
from paper.related_models.paper_model import Paper
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from user.models import User


class CommentSignalsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="user1")
        self.paper = Paper.objects.create(title="paper1")
        self.hub1 = Hub.objects.create(name="hub1")
        self.hub2 = Hub.objects.create(name="hub2")
        self.paper.unified_document.hubs.add(self.hub1)
        self.paper.unified_document.hubs.add(self.hub2)

        self.content_type = ContentType.objects.get_for_model(Paper)
        self.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=self.content_type,
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "comment1"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=self.thread,
        )

    @patch("feed.signals.comment_signals.refresh_feed_entries_for_objects")
    def test_handle_comment_update_metrics(self, mock_refresh_feed_entries_for_objects):
        """
        Test that feed metrics are updated when a comment is updated.
        """
        # Arrange
        mock_refresh_feed_entries_for_objects.apply_async = MagicMock()

        # Act
        RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "reply1"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
            parent=self.comment,
        )
        RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "reply2"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
            parent=self.comment,
        )

        # Assert
        # The paper metrics should show 0 replies because:
        # 1. The thread has a PEER_REVIEW root comment, not GENERIC_COMMENT
        # 2. Only GENERIC_COMMENT threads with GENERIC_COMMENT roots are counted in discussions
        mock_refresh_feed_entries_for_objects.apply_async.assert_has_calls(
            [
                call(
                    args=(self.paper.id,),
                    priority=1,
                ),
            ]
        )
