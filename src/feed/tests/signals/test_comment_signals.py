from unittest.mock import MagicMock, call, patch

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

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
from utils.test_helpers import AWSMockTestCase, AWSMockTransactionTestCase


class CommentSignalsTests(AWSMockTestCase):
    def setUp(self):
        super().setUp()
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

    @patch("feed.signals.comment_signals.create_feed_entry")
    @patch(
        "feed.signals.comment_signals.transaction.on_commit",
        side_effect=lambda fn: fn(),
    )
    def test_handle_comment_created_signal(
        self, mock_on_commit, mock_create_feed_entry
    ):
        """
        Test that a feed entry is created when a new comment is created.
        """
        mock_create_feed_entry.apply_async = MagicMock()

        new_comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "new comment"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
        )

        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        hub_ids = list(self.paper.unified_document.hubs.values_list("id", flat=True))

        mock_create_feed_entry.apply_async.assert_called_once_with(
            args=(
                new_comment.id,
                comment_ct.id,
                FeedEntry.PUBLISH,
                hub_ids,
                self.user.id,
            ),
            priority=1,
        )

    @patch("feed.signals.comment_signals.delete_feed_entry")
    @patch(
        "feed.signals.comment_signals.transaction.on_commit",
        side_effect=lambda fn: fn(),
    )
    def test_handle_comment_removed_signal(
        self, mock_on_commit, mock_delete_feed_entry
    ):
        """
        Test that a feed entry is deleted when a comment is removed.
        """
        mock_delete_feed_entry.apply_async = MagicMock()

        self.comment.is_removed = True
        self.comment.save()

        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        hub_ids = list(self.paper.unified_document.hubs.values_list("id", flat=True))

        mock_delete_feed_entry.apply_async.assert_called_once_with(
            args=(
                self.comment.id,
                comment_ct.id,
                hub_ids,
            ),
            priority=1,
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

        content_type = ContentType.objects.get_for_model(self.paper)

        # Assert
        # The paper metrics should show 0 replies because:
        # 1. The thread has a PEER_REVIEW root comment, not GENERIC_COMMENT
        # 2. Only GENERIC_COMMENT threads with GENERIC_COMMENT roots are counted in
        # discussions
        mock_refresh_feed_entries_for_objects.apply_async.assert_has_calls(
            [
                call(
                    args=(self.paper.id, content_type.id),
                    priority=1,
                ),
            ]
        )


class CommentUpdateFeedRefreshTests(AWSMockTransactionTestCase):
    """
    Uses AWSMockTransactionTestCase so the real transaction.on_commit() hook runs.
    TestCase never commits, which would skip the refresh scheduled when a comment
    is edited.
    """

    def setUp(self):
        super().setUp()
        self.create_patcher = patch("feed.signals.comment_signals.create_feed_entry")
        self.mock_create_feed_entry = self.create_patcher.start()
        self.mock_create_feed_entry.apply_async = MagicMock()
        self.addCleanup(self.create_patcher.stop)

        self.refresh_patcher = patch(
            "feed.signals.comment_signals.refresh_feed_entries_for_objects"
        )
        self.mock_refresh = self.refresh_patcher.start()
        self.mock_refresh.apply_async = MagicMock()
        self.addCleanup(self.refresh_patcher.stop)

        self.user = User.objects.create_user(username="user1")
        self.paper = Paper.objects.create(title="paper1")
        self.hub1 = Hub.objects.create(name="hub1")
        self.hub2 = Hub.objects.create(name="hub2")
        self.paper.unified_document.hubs.add(self.hub1, self.hub2)

        self.thread = RhCommentThreadModel.objects.create(
            thread_type=PEER_REVIEW,
            content_type=ContentType.objects.get_for_model(Paper),
            object_id=self.paper.id,
            created_by=self.user,
        )
        self.comment = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "comment1"}]},
            comment_type=PEER_REVIEW,
            created_by=self.user,
            thread=self.thread,
        )
        self.reply = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "reply"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
            parent=self.comment,
        )
        self.nested_reply = RhCommentModel.objects.create(
            comment_content_json={"ops": [{"insert": "nested reply"}]},
            comment_type=GENERIC_COMMENT,
            created_by=self.user,
            thread=self.thread,
            parent=self.reply,
        )
        self.comment_content_type = ContentType.objects.get_for_model(RhCommentModel)
        self.paper_content_type = ContentType.objects.get_for_model(self.paper)
        self.mock_refresh.apply_async.reset_mock()

    def _refresh_calls(self):
        return [
            call_args.kwargs["args"]
            for call_args in self.mock_refresh.apply_async.call_args_list
        ]

    def test_comment_update_refreshes_comment_and_direct_replies_after_commit(self):
        """
        Editing a comment rewrites its feed snapshot, and the snapshots of
        replies that quote it, only after the edit commits.
        """
        # Act
        with transaction.atomic():
            self.comment.comment_content_json = {"ops": [{"insert": "edited"}]}
            self.comment.save()

            # The parent document refresh is immediate. Comment snapshots stay
            # queued until this block commits.
            self.assertEqual(
                self._refresh_calls(),
                [(self.paper.id, self.paper_content_type.id)],
            )

        # Assert
        self.mock_refresh.apply_async.assert_has_calls(
            [
                call(
                    args=(self.comment.id, self.comment_content_type.id),
                    priority=1,
                ),
                call(
                    args=(self.reply.id, self.comment_content_type.id),
                    priority=1,
                ),
                call(
                    args=(self.paper.id, self.paper_content_type.id),
                    priority=1,
                ),
            ],
            any_order=True,
        )
        self.assertEqual(self.mock_refresh.apply_async.call_count, 3)
        refreshed_comment_ids = [
            item_id
            for item_id, content_type_id in self._refresh_calls()
            if content_type_id == self.comment_content_type.id
        ]
        self.assertNotIn(self.nested_reply.id, refreshed_comment_ids)

    def test_comment_update_does_not_refresh_comment_snapshots_on_rollback(self):
        """
        A rolled-back edit does not enqueue refreshes for the comment or its replies.
        """
        # Act
        with self.assertRaises(RuntimeError), transaction.atomic():
            self.comment.comment_content_json = {"ops": [{"insert": "edited"}]}
            self.comment.save()
            raise RuntimeError("rollback")

        # Assert
        refreshed_comment_ids = [
            item_id
            for item_id, content_type_id in self._refresh_calls()
            if content_type_id == self.comment_content_type.id
        ]
        self.assertEqual(refreshed_comment_ids, [])

    def test_enqueue_failure_still_refreshes_later_comments(self):
        """
        A failed enqueue does not stop later comments or raise after the edit commits.
        """

        def apply_async(*, args, priority):
            item_id, content_type_id = args
            if (
                item_id == self.comment.id
                and content_type_id == self.comment_content_type.id
            ):
                raise ConnectionError("broker down")

        self.mock_refresh.apply_async.side_effect = apply_async

        # Act
        with transaction.atomic():
            self.comment.comment_content_json = {"ops": [{"insert": "edited"}]}
            self.comment.save()

        # Assert
        self.comment.refresh_from_db()
        self.assertEqual(
            self.comment.comment_content_json,
            {"ops": [{"insert": "edited"}]},
        )
        refreshed_comment_ids = [
            item_id
            for item_id, content_type_id in self._refresh_calls()
            if content_type_id == self.comment_content_type.id
        ]
        self.assertIn(self.reply.id, refreshed_comment_ids)
        self.assertNotIn(self.nested_reply.id, refreshed_comment_ids)
