from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from analytics.models import UserInteractions
from discussion.models import Vote
from hub.tests.helpers import create_hub
from personalize.tasks import create_list_item_interaction_task
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from user.tests.helpers import create_random_default_user
from user_lists.models import List, ListItem


class UnifiedDocumentSignalTests(TestCase):
    """Tests for unified document hub changes triggering personalize sync."""

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_queues_task_when_hubs_added(self, mock_sync_task):
        """Adding hubs to a unified document should queue the sync task."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )
        hub = create_hub(name="Test Hub")

        mock_sync_task.reset_mock()

        # Adding hub should trigger the signal
        unified_doc.hubs.add(hub)

        mock_sync_task.delay.assert_called_once_with(unified_doc.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_does_not_queue_on_creation_without_hubs(self, mock_sync_task):
        """Creating a unified document without hubs should not trigger sync."""
        ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )

        mock_sync_task.delay.assert_not_called()

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_queues_task_when_hubs_removed(self, mock_sync_task):
        """Removing hubs should trigger sync to update Personalize."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )
        hub = create_hub(name="Test Hub Remove")
        unified_doc.hubs.add(hub)

        mock_sync_task.reset_mock()

        # Removing hub should trigger the signal
        unified_doc.hubs.remove(hub)

        mock_sync_task.delay.assert_called_once_with(unified_doc.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_queues_task_when_hubs_cleared(self, mock_sync_task):
        """Clearing all hubs should trigger sync to update Personalize."""
        unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION", is_removed=False
        )
        hub1 = create_hub(name="Test Hub Clear 1")
        hub2 = create_hub(name="Test Hub Clear 2")
        unified_doc.hubs.add(hub1, hub2)

        mock_sync_task.reset_mock()

        # Clearing hubs should trigger the signal
        unified_doc.hubs.clear()

        mock_sync_task.delay.assert_called_once_with(unified_doc.id)

    @patch(
        "personalize.signals.unified_document_signals"
        ".sync_unified_document_to_personalize_task"
    )
    def test_signal_triggers_when_hubs_added_to_post(self, mock_sync_task):
        """Adding hubs to a post's unified document queues the sync task."""
        user = create_random_default_user("post_signal_user")
        post = create_post(created_by=user)
        hub = create_hub(name="Post Hub")

        mock_sync_task.reset_mock()

        # Adding hub should trigger the signal
        post.unified_document.hubs.add(hub)

        mock_sync_task.delay.assert_called_with(post.unified_document.id)


class VoteSignalTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("vote_test_user")
        self.post = create_post(created_by=self.user)
        self.content_type = ContentType.objects.get_for_model(self.post)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_queues_task_on_upvote_creation(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.UPVOTE,
        )

        mock_task.delay.assert_called_once_with(vote.id)

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_skips_on_downvote_creation(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        mock_task.delay.assert_not_called()

    @patch("personalize.signals.vote_signals.create_upvote_interaction_task")
    @patch("personalize.signals.vote_signals.transaction")
    def test_signal_skips_on_vote_update(self, mock_transaction, mock_task):
        mock_transaction.on_commit = lambda func: func()

        vote = Vote.objects.create(
            created_by=self.user,
            content_type=self.content_type,
            object_id=self.post.id,
            vote_type=Vote.DOWNVOTE,
        )

        mock_task.reset_mock()

        vote.vote_type = Vote.UPVOTE
        vote.save()

        mock_task.delay.assert_not_called()


class ListSaveSignalTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("list_test_user")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type="DISCUSSION"
        )
        self.list = List.objects.create(name="Test List", created_by=self.user)

    @patch("personalize.signals.list_signals.create_list_item_interaction_task")
    @patch("personalize.signals.list_signals.transaction")
    def test_signal_queues_task_on_list_item_creation(
        self, mock_transaction, mock_task
    ):
        mock_transaction.on_commit = lambda func: func()

        list_item = ListItem.objects.create(
            parent_list=self.list,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mock_task.delay.assert_called_once_with(list_item.id)

    @patch("personalize.signals.list_signals.create_list_item_interaction_task")
    @patch("personalize.signals.list_signals.transaction")
    def test_signal_does_not_queue_task_on_list_item_removal(
        self, mock_transaction, mock_task
    ):
        mock_transaction.on_commit = lambda func: func()

        list_item = ListItem.objects.create(
            parent_list=self.list,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        mock_task.reset_mock()

        # Removal (soft delete) should not trigger the signal (it's an update)
        list_item.is_removed = True
        list_item.save()

        mock_task.delay.assert_not_called()

    def test_list_item_creation_leads_to_user_interaction_record_creation(self):
        list_item = ListItem.objects.create(
            parent_list=self.list,
            unified_document=self.unified_doc,
            created_by=self.user,
        )

        # Manually trigger the task to verify its internal logic
        create_list_item_interaction_task(list_item.id)

        self.assertTrue(
            UserInteractions.objects.filter(
                user=self.user,
                event="DOCUMENT_SAVED_TO_LIST",
                unified_document=self.unified_doc,
            ).exists()
        )
