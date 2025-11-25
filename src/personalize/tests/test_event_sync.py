from datetime import datetime
from unittest.mock import Mock, PropertyMock, patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from analytics.constants.event_types import (
    COMMENT_CREATED,
    FEED_ITEM_CLICK,
    PAGE_VIEW,
    PEER_REVIEW_CREATED,
    UPVOTE,
)
from analytics.models import UserInteractions
from analytics.services.event_processor import EventProcessor
from analytics.tests.helpers import create_prefetched_paper
from discussion.models import Vote
from personalize.clients.sync_client import SyncClient
from personalize.tasks import (
    create_comment_interaction_task,
    create_upvote_interaction_task,
)
from personalize.utils.personalize_utils import (
    build_session_id_for_anonymous,
    build_session_id_for_user,
)
from researchhub_comment.constants.rh_comment_thread_types import (
    GENERIC_COMMENT,
    PEER_REVIEW,
)
from researchhub_comment.models import RhCommentModel
from researchhub_document.helpers import create_post
from user.tests.helpers import create_random_default_user


class EventSyncTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("test_user")
        self.paper = create_prefetched_paper(title="Test Paper")
        self.content_type = ContentType.objects.get_for_model(self.paper.paper)

        self.mock_sync_result_success = {
            "success": True,
            "synced": 1,
            "failed": 0,
            "errors": [],
        }

        self.mock_sync_result_failure = {
            "success": False,
            "synced": 0,
            "failed": 1,
            "errors": ["AWS API error"],
        }

    def _create_amplitude_event(self, event_type, timestamp_offset=0):
        return {
            "event_type": event_type,
            "event_properties": {
                "user_id": str(self.user.id),
                "related_work": {
                    "unified_document_id": str(self.paper.id),
                    "content_type": "paper",
                    "id": str(self.paper.paper.id),
                },
            },
            "_time": int(
                (datetime.now(pytz.UTC).timestamp() + timestamp_offset) * 1000
            ),
        }

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_only_specific_events_synced_from_amplitude(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        processor = EventProcessor()
        feed_click_event = self._create_amplitude_event("feed_item_clicked")
        page_view_event = self._create_amplitude_event("work_document_viewed", 1)

        # Act
        processor.process_event(feed_click_event)
        processor.process_event(page_view_event)

        # Assert
        self.assertEqual(mock_service.sync_event.call_count, 2)
        synced_interactions = UserInteractions.objects.filter(
            user=self.user, unified_document=self.paper
        )
        self.assertEqual(synced_interactions.count(), 2)
        event_types = set(synced_interactions.values_list("event", flat=True))
        self.assertIn(FEED_ITEM_CLICK, event_types)
        self.assertIn(PAGE_VIEW, event_types)
        self.assertNotIn(UPVOTE, event_types)

    @patch("personalize.clients.sync_client.create_client")
    @patch("personalize.clients.sync_client.settings")
    def test_sync_client_creates_correct_batches_for_events(
        self, mock_settings, mock_create_client
    ):
        # Arrange
        mock_aws_client = Mock()
        mock_create_client.return_value = mock_aws_client
        mock_settings.AWS_PERSONALIZE_DATASET_ARN = "arn:test:dataset"
        mock_settings.AWS_PERSONALIZE_TRACKING_ID = "test-tracking-id"

        sync_client = SyncClient()
        events = [
            {
                "eventId": str(i),
                "eventType": "FEED_ITEM_CLICK",
                "itemId": "123",
                "sentAt": int(datetime.now().timestamp()),
            }
            for i in range(25)
        ]

        # Act
        result = sync_client.put_events("user_123", "sess_user_123_2025_11_18", events)

        # Assert
        self.assertEqual(mock_aws_client.put_events.call_count, 3)
        call_args_list = mock_aws_client.put_events.call_args_list
        self.assertEqual(len(call_args_list[0][1]["eventList"]), 10)
        self.assertEqual(len(call_args_list[1][1]["eventList"]), 10)
        self.assertEqual(len(call_args_list[2][1]["eventList"]), 5)
        self.assertEqual(result["synced"], 25)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["success"])

    def test_session_id_formatting_for_authenticated_users(self):
        # Arrange
        user_id = 12345
        test_date = datetime(2025, 11, 18, 14, 30, 0, tzinfo=pytz.UTC)

        # Act
        session_id = build_session_id_for_user(user_id, test_date)

        # Assert
        self.assertEqual(session_id, "sess_user_12345_2025_11_18")

        different_date = datetime(2025, 11, 19, 10, 0, 0, tzinfo=pytz.UTC)
        different_session = build_session_id_for_user(user_id, different_date)
        self.assertNotEqual(session_id, different_session)
        self.assertEqual(different_session, "sess_user_12345_2025_11_19")

    def test_session_id_formatting_for_anonymous_users(self):
        # Arrange
        external_user_id = "amp_anon_xyz789"

        # Act
        session_id = build_session_id_for_anonymous(external_user_id)

        # Assert
        self.assertEqual(session_id, f"sess_anon_{external_user_id}")
        self.assertRegex(session_id, r"^sess_anon_.+$")

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_sync_only_triggered_when_interaction_created(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        processor = EventProcessor()
        event_payload = self._create_amplitude_event("feed_item_clicked")

        # Act
        processor.process_event(event_payload)
        first_call_count = mock_service.sync_event.call_count

        processor.process_event(event_payload)
        second_call_count = mock_service.sync_event.call_count

        # Assert
        self.assertEqual(first_call_count, 1)
        self.assertEqual(second_call_count, 1)
        interactions = UserInteractions.objects.filter(
            user=self.user, unified_document=self.paper, event=FEED_ITEM_CLICK
        )
        self.assertEqual(interactions.count(), 1)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_interaction_marked_as_synced_on_success(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_success
        MockSyncService.return_value = mock_service

        # Act - Creating UserInteraction should trigger signal which calls sync task
        interaction = UserInteractions.objects.create(
            user=self.user,
            event=FEED_ITEM_CLICK,
            unified_document=self.paper,
            content_type=self.content_type,
            object_id=self.paper.paper.id,
            event_timestamp=datetime.now(pytz.UTC),
            is_synced_with_personalize=False,
        )

        # Assert
        mock_service.sync_event.assert_called_once()
        interaction.refresh_from_db()
        self.assertTrue(interaction.is_synced_with_personalize)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.SyncService")
    def test_interaction_not_marked_synced_on_failure(self, MockSyncService):
        # Arrange
        mock_service = Mock()
        mock_service.sync_event.return_value = self.mock_sync_result_failure
        MockSyncService.return_value = mock_service

        # Act - Creating UserInteraction should trigger signal which calls sync task
        interaction = UserInteractions.objects.create(
            user=self.user,
            event=PAGE_VIEW,
            unified_document=self.paper,
            content_type=self.content_type,
            object_id=self.paper.paper.id,
            event_timestamp=datetime.now(pytz.UTC),
            is_synced_with_personalize=False,
        )

        # Assert
        mock_service.sync_event.assert_called_once()
        interaction.refresh_from_db()
        self.assertFalse(interaction.is_synced_with_personalize)


class UpvoteInteractionTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("upvote_task_test_user")
        self.post_owner = create_random_default_user("post_owner_user")
        self.post = create_post(created_by=self.post_owner)
        self.content_type = ContentType.objects.get_for_model(self.post)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    def test_create_upvote_interaction_task_creates_user_interaction(
        self, mock_sync_signal, mock_vote_signal
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, UPVOTE)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(interaction.content_type, self.content_type)
        self.assertEqual(interaction.object_id, self.post.id)
        self.assertFalse(interaction.is_synced_with_personalize)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    def test_create_upvote_interaction_task_handles_duplicate(
        self, mock_sync_signal, mock_vote_signal
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        create_upvote_interaction_task(vote.id)
        initial_count = UserInteractions.objects.count()

        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_create_upvote_interaction_task_skips_non_upvote(self):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_create_upvote_interaction_task_handles_missing_vote(self):
        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(99999)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.Vote.objects.get")
    def test_create_upvote_interaction_task_skips_vote_without_user(
        self, mock_vote_get
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )
        # Mock vote to have no created_by_id
        vote.created_by_id = None
        mock_vote_get.return_value = vote

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.Vote.objects.get")
    def test_create_upvote_interaction_task_handles_unified_doc_exception(
        self, mock_vote_get
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )
        mock_vote_get.return_value = vote

        # Mock unified_document property to raise an exception
        with patch.object(
            Vote, "unified_document", new_callable=PropertyMock
        ) as mock_unified_doc:
            mock_unified_doc.side_effect = Exception("No unified doc")

            initial_count = UserInteractions.objects.count()
            create_upvote_interaction_task(vote.id)
            final_count = UserInteractions.objects.count()

            self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.Vote.objects.get")
    def test_create_upvote_interaction_task_handles_none_unified_document(
        self, mock_vote_get
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )
        mock_vote_get.return_value = vote

        # Mock unified_document property to return None
        with patch.object(
            Vote, "unified_document", new_callable=PropertyMock
        ) as mock_unified_doc:
            mock_unified_doc.return_value = None

            initial_count = UserInteractions.objects.count()
            create_upvote_interaction_task(vote.id)
            final_count = UserInteractions.objects.count()

            self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.map_from_upvote")
    def test_create_upvote_interaction_task_handles_mapping_exception(
        self, mock_map_from_upvote
    ):
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        # Mock map_from_upvote to raise an exception
        mock_map_from_upvote.side_effect = Exception("Mapping failed")

        initial_count = UserInteractions.objects.count()
        with self.assertRaises(Exception):
            create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    @patch("personalize.signals.vote_signals.create_upvote_interaction")
    def test_create_upvote_interaction_task_skips_self_upvote_on_post(
        self, mock_vote_signal, mock_interaction_signal
    ):
        # Create a post by the same user
        self_post = create_post(created_by=self.user)
        content_type = ContentType.objects.get_for_model(self_post)

        # User upvotes their own post
        vote = Vote.objects.create(
            created_by=self.user,
            content_type=content_type,
            object_id=self_post.id,
            vote_type=Vote.UPVOTE,
        )

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        # Should not create UserInteraction for self-upvote
        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    @patch("personalize.signals.vote_signals.create_upvote_interaction")
    def test_create_upvote_interaction_task_skips_self_upvote_on_paper(
        self, mock_vote_signal, mock_interaction_signal
    ):
        paper = create_prefetched_paper(title="Test Paper", user=self.user)
        content_type = ContentType.objects.get_for_model(paper.paper)

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=content_type,
            object_id=paper.paper.id,
            vote_type=Vote.UPVOTE,
        )

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        # Should not create UserInteraction for self-upvote
        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    @patch("personalize.signals.vote_signals.create_upvote_interaction")
    def test_create_upvote_interaction_task_creates_interaction_for_other_user_upvote(
        self, mock_vote_signal, mock_interaction_signal
    ):
        other_user = create_random_default_user("other_user")
        other_post = create_post(created_by=other_user)
        content_type = ContentType.objects.get_for_model(other_post)

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=content_type,
            object_id=other_post.id,
            vote_type=Vote.UPVOTE,
        )

        initial_count = UserInteractions.objects.count()
        create_upvote_interaction_task(vote.id)
        final_count = UserInteractions.objects.count()

        # Should create UserInteraction for upvote on someone else's document
        self.assertEqual(final_count, initial_count + 1)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, UPVOTE)
        self.assertEqual(interaction.unified_document, other_post.unified_document)


class CommentInteractionTaskTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("comment_task_test_user")
        self.post_owner = create_random_default_user("post_owner_user")
        self.post = create_post(created_by=self.post_owner)

    def _create_comment(self, comment_type=GENERIC_COMMENT, created_by=None):
        """Helper to create a comment on the post."""
        if created_by is None:
            created_by = self.user

        # Get or create thread for the post
        from researchhub_comment.models import RhCommentThreadModel

        thread, _ = RhCommentThreadModel.objects.get_or_create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            defaults={"created_by": created_by},
        )

        comment = RhCommentModel.objects.create(
            created_by=created_by,
            thread=thread,
            comment_type=comment_type,
            comment_content_json={"ops": [{"insert": "Test comment"}]},
        )
        return comment

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.comment_signals.create_comment_interaction_task")
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    def test_create_comment_interaction_task_creates_comment_user_interaction(
        self, mock_sync_signal, mock_comment_signal
    ):
        comment = self._create_comment(comment_type=GENERIC_COMMENT)

        initial_count = UserInteractions.objects.count()
        create_comment_interaction_task(comment.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, COMMENT_CREATED)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(
            interaction.content_type, ContentType.objects.get_for_model(RhCommentModel)
        )
        self.assertEqual(interaction.object_id, comment.id)
        self.assertFalse(interaction.is_synced_with_personalize)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.comment_signals.create_comment_interaction_task")
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    def test_create_comment_interaction_task_creates_peer_review_user_interaction(
        self, mock_sync_signal, mock_comment_signal
    ):
        comment = self._create_comment(comment_type=PEER_REVIEW)

        initial_count = UserInteractions.objects.count()
        create_comment_interaction_task(comment.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count + 1)

        interaction = UserInteractions.objects.latest("created_date")
        self.assertEqual(interaction.user, self.user)
        self.assertEqual(interaction.event, PEER_REVIEW_CREATED)
        self.assertEqual(interaction.unified_document, self.post.unified_document)
        self.assertEqual(
            interaction.content_type, ContentType.objects.get_for_model(RhCommentModel)
        )
        self.assertEqual(interaction.object_id, comment.id)
        self.assertFalse(interaction.is_synced_with_personalize)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.signals.comment_signals.create_comment_interaction_task")
    @patch("personalize.signals.interaction_signals.sync_interaction_to_personalize")
    def test_create_comment_interaction_task_is_idempotent(
        self, mock_sync_signal, mock_comment_signal
    ):
        comment = self._create_comment()

        create_comment_interaction_task(comment.id)
        initial_count = UserInteractions.objects.count()

        # Call again - should not create duplicate
        create_comment_interaction_task(comment.id)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_create_comment_interaction_task_handles_missing_comment(self):
        initial_count = UserInteractions.objects.count()
        create_comment_interaction_task(99999)
        final_count = UserInteractions.objects.count()

        self.assertEqual(final_count, initial_count)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    def test_create_comment_interaction_task_handles_none_unified_document(self):
        comment = self._create_comment()

        # Mock unified_document property to return None
        with patch.object(
            RhCommentModel, "unified_document", new_callable=PropertyMock
        ) as mock_unified_doc:
            mock_unified_doc.return_value = None

            initial_count = UserInteractions.objects.count()
            create_comment_interaction_task(comment.id)
            final_count = UserInteractions.objects.count()

            self.assertEqual(final_count, initial_count)

    def test_map_from_comment_raises_exception_on_unified_doc_error(self):
        """Test that mapper raises exception when unified_document property fails."""
        from analytics.interactions.interaction_mapper import map_from_comment

        comment = self._create_comment()

        # Mock unified_document to raise an exception
        with patch.object(
            RhCommentModel, "unified_document", new_callable=PropertyMock
        ) as mock_unified_doc:
            mock_unified_doc.side_effect = Exception("Database error")

            with self.assertRaises(Exception) as context:
                map_from_comment(comment)

            self.assertIn("Database error", str(context.exception))

    def test_map_from_comment_raises_on_missing_attributes(self):
        """Test that mapper raises AttributeError when comment lacks attributes."""
        from analytics.interactions.interaction_mapper import map_from_comment

        # Create a mock object without the created_date attribute
        mock_comment = Mock(spec=[])  # Empty spec means no attributes
        mock_comment.id = 999
        mock_comment.comment_type = GENERIC_COMMENT
        mock_comment.created_by = None
        mock_comment.unified_document = None
        # Don't set created_date - this will raise AttributeError

        with self.assertRaises(AttributeError):
            map_from_comment(mock_comment)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("personalize.tasks.log_error")
    @patch("personalize.tasks.map_from_comment")
    def test_create_comment_interaction_task_logs_mapper_exceptions_to_sentry(
        self, mock_map, mock_log_error
    ):
        """Test that task catches mapper exceptions and logs them to Sentry."""
        comment = self._create_comment()

        # Make mapper raise an exception
        mock_map.side_effect = Exception("Mapper failed unexpectedly")

        # Task should catch exception, log to Sentry, and re-raise
        with self.assertRaises(Exception) as context:
            create_comment_interaction_task(comment.id)

        # Verify the exception message
        self.assertIn("Mapper failed unexpectedly", str(context.exception))

        # Verify log_error was called to log to Sentry
        mock_log_error.assert_called_once()
        call_args = mock_log_error.call_args

        # First argument should be the exception
        self.assertIsInstance(call_args[0][0], Exception)
        self.assertIn("Mapper failed unexpectedly", str(call_args[0][0]))

        # Should have a message keyword argument with comment_id
        self.assertIn("message", call_args[1])
        self.assertIn(str(comment.id), call_args[1]["message"])

        # No UserInteraction should have been created
        interactions = UserInteractions.objects.filter(object_id=comment.id)
        self.assertEqual(interactions.count(), 0)
