"""
Tests for the generic feed management system.

These tests verify that the new feed manager correctly handles:
- Entity registration
- Feed entry creation/deletion
- Hub association changes
- Metric updates for related entities
"""

import unittest
from unittest.mock import MagicMock, Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.feed_manager import FeedConfig, FeedManager, feed_manager
from feed.models import FeedEntry


class TestFeedManager(TestCase):
    def setUp(self):
        self.manager = FeedManager()

        # Create a proper mock model class
        class MockModel:
            pass

        self.mock_model = MockModel

        # Create a basic config
        self.config = FeedConfig(
            model_class=self.mock_model,
            feed_actions=[FeedEntry.PUBLISH],
            get_unified_document=lambda x: getattr(x, "unified_document", Mock()),
            get_hub_ids=lambda x: [1, 2, 3],  # Always return non-empty list for tests
            get_user=lambda x: getattr(x, "created_by", Mock()),
        )

    def test_register_entity_type(self):
        """Test registering an entity type with the feed manager."""
        self.manager.register_entity_type(self.config)

        self.assertTrue(self.manager.is_registered(self.mock_model))
        self.assertEqual(self.manager.get_config(self.mock_model), self.config)

    def test_is_registered(self):
        """Test checking if an entity type is registered."""
        # Not registered initially
        self.assertFalse(self.manager.is_registered(self.mock_model))

        # Register and check again
        self.manager.register_entity_type(self.config)
        self.assertTrue(self.manager.is_registered(self.mock_model))

    def test_get_config(self):
        """Test getting configuration for a model class."""
        # No config initially
        self.assertIsNone(self.manager.get_config(self.mock_model))

        # Register and get config
        self.manager.register_entity_type(self.config)
        self.assertEqual(self.manager.get_config(self.mock_model), self.config)

    @patch("feed.feed_manager.transaction")
    @patch("feed.feed_manager.ContentType")
    @patch("feed.feed_manager.create_feed_entry")
    def test_handle_entity_created(
        self, mock_create_feed, mock_content_type, mock_transaction
    ):
        """Test handling entity creation."""
        # Set up mocks
        mock_instance = self.mock_model()
        mock_instance.id = 1
        mock_instance.unified_document = Mock()
        mock_instance.created_by = Mock()
        mock_instance.created_by.id = 1

        mock_content_type.objects.get_for_model.return_value.id = 1
        mock_transaction.on_commit = lambda func: func()

        # Register config and handle creation
        self.manager.register_entity_type(self.config)
        self.manager.handle_entity_created(mock_instance, created=True)

        # Verify create_feed_entry was called
        mock_create_feed.apply_async.assert_called_once()
        call_args = mock_create_feed.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], 1)  # instance.id
        self.assertEqual(call_args[1]["args"][2], FeedEntry.PUBLISH)  # action
        self.assertEqual(call_args[1]["args"][3], [1, 2, 3])  # hub_ids
        self.assertEqual(call_args[1]["args"][4], 1)  # user_id

    @patch("feed.feed_manager.transaction")
    @patch("feed.feed_manager.ContentType")
    @patch("feed.feed_manager.delete_feed_entry")
    def test_handle_entity_removed(
        self, mock_delete_feed, mock_content_type, mock_transaction
    ):
        """Test handling entity removal."""
        # Set up mocks
        mock_instance = self.mock_model()
        mock_instance.id = 1

        mock_content_type.objects.get_for_model.return_value.id = 1
        mock_transaction.on_commit = lambda func: func()

        # Register config and handle removal
        self.manager.register_entity_type(self.config)
        self.manager.handle_entity_removed(mock_instance)

        # Verify delete_feed_entry was called
        mock_delete_feed.apply_async.assert_called_once()
        call_args = mock_delete_feed.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], 1)  # instance.id
        self.assertEqual(call_args[1]["args"][1], 1)  # content_type.id

    @patch("feed.feed_manager.transaction")
    @patch("feed.feed_manager.ContentType")
    @patch("feed.feed_manager.create_feed_entry")
    def test_handle_hubs_changed_add(
        self, mock_create_feed, mock_content_type, mock_transaction
    ):
        """Test handling hub additions."""
        # Set up mocks
        mock_instance = self.mock_model()
        mock_instance.id = 1
        mock_instance.created_by = Mock()
        mock_instance.created_by.id = 1

        mock_content_type.objects.get_for_model.return_value.id = 1
        mock_transaction.on_commit = lambda func: func()

        # Register config and handle hub change
        self.manager.register_entity_type(self.config)
        self.manager.handle_hubs_changed(mock_instance, "post_add", {4, 5})

        # Verify create_feed_entry was called
        mock_create_feed.apply_async.assert_called_once()
        call_args = mock_create_feed.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], 1)  # instance.id
        self.assertEqual(call_args[1]["args"][2], FeedEntry.PUBLISH)  # action
        self.assertEqual(call_args[1]["args"][3], [4, 5])  # hub_ids

    @patch("feed.feed_manager.transaction")
    @patch("feed.feed_manager.ContentType")
    @patch("feed.feed_manager.delete_feed_entry")
    def test_handle_hubs_changed_remove(
        self, mock_delete_feed, mock_content_type, mock_transaction
    ):
        """Test handling hub removals."""
        # Set up mocks
        mock_instance = self.mock_model()
        mock_instance.id = 1

        mock_content_type.objects.get_for_model.return_value.id = 1
        mock_transaction.on_commit = lambda func: func()

        # Register config and handle hub change
        self.manager.register_entity_type(self.config)
        self.manager.handle_hubs_changed(mock_instance, "post_remove", {4, 5})

        # Verify delete_feed_entry was called
        mock_delete_feed.apply_async.assert_called_once()
        call_args = mock_delete_feed.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], 1)  # instance.id
        self.assertEqual(call_args[1]["args"][2], [4, 5])  # hub_ids

    def test_handle_unregistered_entity(self):
        """Test that unregistered entities are ignored."""
        mock_instance = Mock()
        # Don't register this instance's class, so it should be ignored

        # Should not raise an error
        self.manager.handle_entity_created(mock_instance, created=True)
        self.manager.handle_entity_removed(mock_instance)
        self.manager.handle_hubs_changed(mock_instance, "post_add", {1, 2})

    @patch("feed.tasks.refresh_feed_entries_for_objects")
    @patch("feed.feed_manager.ContentType")
    def test_refresh_entity_feed_entries(self, mock_content_type, mock_refresh):
        """Test refreshing feed entries for an entity."""
        mock_instance = self.mock_model()
        mock_instance.id = 1

        mock_content_type.objects.get_for_model.return_value.id = 1

        # Register config and refresh
        self.manager.register_entity_type(self.config)
        self.manager.refresh_entity_feed_entries(mock_instance)

        # Verify refresh task was called
        mock_refresh.apply_async.assert_called_once()
        call_args = mock_refresh.apply_async.call_args
        self.assertEqual(call_args[1]["args"][0], 1)  # instance.id
        self.assertEqual(call_args[1]["args"][1], 1)  # content_type.id


class TestFeedConfig(TestCase):
    def test_feed_config_creation(self):
        """Test creating a FeedConfig with various options."""
        mock_model = Mock()

        config = FeedConfig(
            model_class=mock_model,
            feed_actions=[FeedEntry.PUBLISH, FeedEntry.OPEN],
            get_unified_document=lambda x: x.unified_document,
            get_hub_ids=lambda x: [1, 2, 3],
            get_user=lambda x: x.created_by,
            create_on_save=False,
            delete_on_remove=False,
            update_related_metrics=True,
            get_related_entities=lambda x: [x.parent],
        )

        self.assertEqual(config.model_class, mock_model)
        self.assertEqual(config.feed_actions, [FeedEntry.PUBLISH, FeedEntry.OPEN])
        self.assertEqual(config.create_on_save, False)
        self.assertEqual(config.delete_on_remove, False)
        self.assertEqual(config.update_related_metrics, True)
        self.assertIsNotNone(config.get_related_entities)


class TestGlobalFeedManager(TestCase):
    def test_global_feed_manager_exists(self):
        """Test that the global feed manager instance exists."""
        self.assertIsInstance(feed_manager, FeedManager)

    @patch("feed.feed_manager.feed_manager.register_entity_type")
    def test_register_feed_entity_function(self, mock_register):
        """Test the convenience function for registering entities."""
        from feed.feed_manager import register_feed_entity

        mock_config = Mock()
        register_feed_entity(mock_config)

        mock_register.assert_called_once_with(mock_config)


if __name__ == "__main__":
    unittest.main()
