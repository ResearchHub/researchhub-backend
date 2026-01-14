"""
Tests for interaction signals that trigger Personalize sync.
"""

from datetime import datetime
from unittest.mock import patch

from django.db import transaction
from django.test import TestCase, TransactionTestCase

from analytics.constants.event_types import FEED_ITEM_IMPRESSION
from analytics.models import UserInteractions
from personalize.tests.helpers import create_prefetched_paper
from user.tests.helpers import create_random_default_user


class InteractionSignalsTests(TransactionTestCase):
    """Tests for UserInteractions signals."""

    def setUp(self):
        self.user = create_random_default_user("signal_test_user")
        self.doc = create_prefetched_paper(title="Test Paper")

    @patch(
        "personalize.signals.interaction_signals.sync_interaction_event_to_personalize_task.delay"
    )
    def test_impression_signal_triggers_personalize_sync(self, mock_task):
        """Test that creating FEED_ITEM_IMPRESSION triggers sync task."""
        # Create a FEED_ITEM_IMPRESSION interaction
        with transaction.atomic():
            interaction = UserInteractions.objects.create(
                user=self.user,
                event=FEED_ITEM_IMPRESSION,
                unified_document=self.doc,
                content_type=None,
                object_id=None,
                event_timestamp=datetime.now(),
                is_synced_with_personalize=False,
                personalize_rec_id="test-rec-id",
            )

        # Verify the sync task was queued after transaction commits
        mock_task.assert_called_once_with(interaction.id)

    @patch(
        "personalize.signals.interaction_signals.sync_interaction_event_to_personalize_task.delay"
    )
    def test_impression_signal_with_external_user_id(self, mock_task):
        """Test impression signal works with external_user_id."""
        # Create a FEED_ITEM_IMPRESSION with external_user_id
        with transaction.atomic():
            interaction = UserInteractions.objects.create(
                user=None,
                external_user_id="external-user-123",
                event=FEED_ITEM_IMPRESSION,
                unified_document=self.doc,
                content_type=None,
                object_id=None,
                event_timestamp=datetime.now(),
                is_synced_with_personalize=False,
                personalize_rec_id="test-rec-id",
            )

        # Verify the sync task was queued after transaction commits
        mock_task.assert_called_once_with(interaction.id)

    @patch(
        "personalize.signals.interaction_signals.sync_interaction_event_to_personalize_task.delay"
    )
    def test_signal_not_triggered_on_update(self, mock_task):
        """Test that signal is not triggered when updating existing interaction."""
        # Create interaction
        with transaction.atomic():
            interaction = UserInteractions.objects.create(
                user=self.user,
                event=FEED_ITEM_IMPRESSION,
                unified_document=self.doc,
                content_type=None,
                object_id=None,
                event_timestamp=datetime.now(),
                is_synced_with_personalize=False,
            )

        # Clear the mock call from creation
        mock_task.reset_mock()

        # Update the interaction
        with transaction.atomic():
            interaction.is_synced_with_personalize = True
            interaction.save()

        # Verify the sync task was NOT queued again
        mock_task.assert_not_called()

    @patch(
        "personalize.signals.interaction_signals.sync_interaction_event_to_personalize_task.delay"
    )
    def test_signal_skips_interaction_without_unified_document(self, mock_task):
        """Test that signal skips interactions without unified_document_id."""
        # Try to create interaction without unified_document
        # This should fail at DB level due to NOT NULL constraint,
        # but if it somehow succeeds, signal should skip it
        try:
            UserInteractions.objects.create(
                user=self.user,
                event=FEED_ITEM_IMPRESSION,
                unified_document=None,
                content_type=None,
                object_id=None,
                event_timestamp=datetime.now(),
            )
        except Exception:
            # Expected to fail due to NOT NULL constraint
            pass

        # Verify no sync task was queued
        mock_task.assert_not_called()
