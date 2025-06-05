"""
Generic Feed Management System

This module provides a unified approach to handling feed entries for different entity types.
Instead of having separate signal handlers for each entity type, this system:

1. Registers entity types with their feed configuration
2. Provides a single interface for feed operations
3. Automatically handles feed entry creation, updates, and deletion
4. Supports metric updates for related entities
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Type, Union

from django.contrib.contenttypes.models import ContentType
from django.db import models, transaction
from django.db.models.signals import m2m_changed, post_save, pre_save
from django.dispatch import receiver

from feed.models import FeedEntry
from feed.serializers import serialize_feed_metrics
from feed.tasks import create_feed_entry, delete_feed_entry, update_feed_metrics

logger = logging.getLogger(__name__)


@dataclass
class FeedConfig:
    """Configuration for how an entity type should behave in the feed system."""

    # The model class this config applies to
    model_class: Type[models.Model]

    # Which actions should create feed entries (e.g., ['PUBLISH', 'OPEN'])
    feed_actions: List[str]

    # How to get the unified document from an instance
    get_unified_document: callable

    # How to get hub IDs from an instance
    get_hub_ids: callable

    # How to get the user who performed the action (optional)
    get_user: Optional[callable] = None

    # How to get the action date (optional, defaults to created_date)
    get_action_date: Optional[callable] = None

    # Whether this entity should be included in feed when created
    create_on_save: bool = True

    # Whether this entity should be removed from feed when deleted/removed
    delete_on_remove: bool = True

    # Whether to update metrics for related entities when this changes
    update_related_metrics: bool = False

    # Function to get related entities that need metric updates
    get_related_entities: Optional[callable] = None


class FeedManager:
    """
    Central manager for feed operations across different entity types.

    This class handles:
    - Registration of entity types and their feed configurations
    - Generic signal handling for registered entity types
    - Feed entry creation, updates, and deletion
    - Metric updates for related entities
    """

    def __init__(self):
        self._configs: Dict[Type[models.Model], FeedConfig] = {}
        self._signals_connected = False

    def register_entity_type(self, config: FeedConfig):
        """Register an entity type with the feed manager."""
        self._configs[config.model_class] = config

        # Connect signals on first registration
        if not self._signals_connected:
            self._connect_signals()
            self._signals_connected = True

    def get_config(self, model_class: Type[models.Model]) -> Optional[FeedConfig]:
        """Get the feed configuration for a model class."""
        return self._configs.get(model_class)

    def is_registered(self, model_class: Type[models.Model]) -> bool:
        """Check if a model class is registered with the feed manager."""
        return model_class in self._configs

    def handle_entity_created(self, instance: models.Model, created: bool = False):
        """Handle when an entity is created or updated."""
        model_class = type(instance)
        config = self.get_config(model_class)

        if not config or not config.create_on_save:
            return

        if created:
            self._create_feed_entries(instance, config)

        # Update metrics for related entities if configured
        if config.update_related_metrics and config.get_related_entities:
            self._update_related_metrics(instance, config)

    def handle_entity_removed(self, instance: models.Model):
        """Handle when an entity is removed or deleted."""
        model_class = type(instance)
        config = self.get_config(model_class)

        if not config or not config.delete_on_remove:
            return

        self._delete_feed_entries(instance, config)

        # Update metrics for related entities if configured
        if config.update_related_metrics and config.get_related_entities:
            self._update_related_metrics(instance, config)

    def handle_hubs_changed(
        self, instance: models.Model, action: str, pk_set: Set[int]
    ):
        """Handle when an entity's hub associations change."""
        model_class = type(instance)
        config = self.get_config(model_class)

        if not config:
            return

        if action == "post_add":
            self._create_feed_entries_for_hubs(instance, config, list(pk_set))
        elif action == "post_remove":
            self._delete_feed_entries_for_hubs(instance, config, list(pk_set))

    def refresh_entity_feed_entries(self, instance: models.Model):
        """Refresh all feed entries for a specific entity."""
        model_class = type(instance)
        config = self.get_config(model_class)

        if not config:
            return

        content_type = ContentType.objects.get_for_model(model_class)

        from feed.tasks import refresh_feed_entries_for_objects

        refresh_feed_entries_for_objects.apply_async(
            args=(instance.id, content_type.id),
            priority=1,
        )

    def _create_feed_entries(self, instance: models.Model, config: FeedConfig):
        """Create feed entries for an entity."""
        try:
            unified_document = config.get_unified_document(instance)
            if not unified_document:
                return

            hub_ids = config.get_hub_ids(instance)
            if not hub_ids:
                return

            user_id = None
            if config.get_user:
                user = config.get_user(instance)
                if user:
                    user_id = user.id
            content_type = ContentType.objects.get_for_model(instance)

            # Create feed entries for each configured action
            for action in config.feed_actions:
                self._schedule_create_task(
                    instance.id, content_type.id, action, hub_ids, user_id
                )
        except Exception as e:
            logger.error(f"Failed to create feed entries for {instance}: {e}")

    def _create_feed_entries_for_hubs(
        self, instance: models.Model, config: FeedConfig, hub_ids: List[int]
    ):
        """Create feed entries for specific hubs."""
        try:
            user_id = None
            if config.get_user:
                user = config.get_user(instance)
                if user:
                    user_id = user.id

            content_type = ContentType.objects.get_for_model(instance)

            for action in config.feed_actions:
                self._schedule_create_task(
                    instance.id, content_type.id, action, hub_ids, user_id
                )
        except Exception as e:
            logger.error(
                f"Failed to create feed entries for {instance} hubs {hub_ids}: {e}"
            )

    def _delete_feed_entries(self, instance: models.Model, config: FeedConfig):
        """Delete all feed entries for an entity."""
        try:
            content_type = ContentType.objects.get_for_model(instance)
            self._schedule_delete_task(instance.id, content_type.id)
        except Exception as e:
            logger.error(f"Failed to delete feed entries for {instance}: {e}")

    def _delete_feed_entries_for_hubs(
        self, instance: models.Model, config: FeedConfig, hub_ids: List[int]
    ):
        """Delete feed entries for specific hubs."""
        try:
            content_type = ContentType.objects.get_for_model(instance)
            self._schedule_delete_task(instance.id, content_type.id, hub_ids)
        except Exception as e:
            logger.error(
                f"Failed to delete feed entries for {instance} hubs {hub_ids}: {e}"
            )

    def _schedule_create_task(
        self,
        item_id: int,
        content_type_id: int,
        action: str,
        hub_ids: Optional[List[int]] = None,
        user_id: Optional[int] = None,
    ):
        """Schedule a create feed entry task, handling test vs production environments."""
        task_args = (item_id, content_type_id, action, hub_ids, user_id)

        # In test environments with CELERY_TASK_ALWAYS_EAGER=True, transaction.on_commit
        # may not work as expected, so we call the task directly
        from django.conf import settings

        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            create_feed_entry.apply_async(args=task_args, priority=1)
        else:
            transaction.on_commit(
                lambda: create_feed_entry.apply_async(args=task_args, priority=1)
            )

    def _schedule_delete_task(
        self, item_id: int, content_type_id: int, hub_ids: Optional[List[int]] = None
    ):
        """Schedule a delete feed entry task, handling test vs production environments."""
        task_args = (
            (item_id, content_type_id, hub_ids)
            if hub_ids
            else (item_id, content_type_id)
        )

        # In test environments with CELERY_TASK_ALWAYS_EAGER=True, transaction.on_commit
        # may not work as expected, so we call the task directly
        from django.conf import settings

        if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
            delete_feed_entry.apply_async(args=task_args, priority=1)
        else:
            transaction.on_commit(
                lambda: delete_feed_entry.apply_async(args=task_args, priority=1)
            )

    def _update_related_metrics(self, instance: models.Model, config: FeedConfig):
        """Update metrics for entities related to this instance."""
        if not config.get_related_entities:
            return

        try:
            related_entities = config.get_related_entities(instance)

            for entity in related_entities:
                content_type = ContentType.objects.get_for_model(entity)
                metrics = serialize_feed_metrics(entity, content_type)

                update_feed_metrics.apply_async(
                    args=(
                        entity.id,
                        content_type.id,
                        metrics,
                    ),
                    priority=1,
                )
        except Exception as e:
            logger.error(f"Failed to update related metrics for {instance}: {e}")

    def _connect_signals(self):
        """Connect generic signal handlers."""

        @receiver(post_save, dispatch_uid="feed_manager_post_save")
        def handle_post_save(sender, instance, created, **kwargs):
            if self.is_registered(sender):
                self.handle_entity_created(instance, created)

        @receiver(pre_save, dispatch_uid="feed_manager_pre_save")
        def handle_pre_save(sender, instance, **kwargs):
            if self.is_registered(sender) and instance.id:
                # Check if entity is being removed
                try:
                    original = sender.objects.get(id=instance.id)
                    if hasattr(original, "is_removed") and hasattr(
                        instance, "is_removed"
                    ):
                        if not original.is_removed and instance.is_removed:
                            self.handle_entity_removed(instance)
                except sender.DoesNotExist:
                    pass


# Global feed manager instance
feed_manager = FeedManager()


def register_feed_entity(config: FeedConfig):
    """Convenience function to register an entity type with the global feed manager."""
    feed_manager.register_entity_type(config)


# Convenience functions for common patterns
def get_unified_document_default(instance):
    """Default function to get unified document from an instance."""
    return getattr(instance, "unified_document", None)


def get_hub_ids_from_unified_document(instance):
    """Get hub IDs from an instance's unified document."""
    unified_document = get_unified_document_default(instance)
    if unified_document:
        return list(unified_document.hubs.values_list("id", flat=True))
    return []


def get_user_created_by(instance):
    """Get the user who created an instance."""
    return getattr(instance, "created_by", None)


def get_user_uploaded_by(instance):
    """Get the user who uploaded an instance."""
    return getattr(instance, "uploaded_by", None)
