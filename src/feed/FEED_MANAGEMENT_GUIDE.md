# Generic Feed Management System

This document explains how to use the new generic feed management system that replaces the individual signal handlers for different entity types.

## Overview

The new system provides a unified approach to handling feed entries for different entity types. Instead of having separate signal handlers for each entity type (posts, comments, papers, etc.), the system uses:

1. **A central FeedManager** that handles all feed operations
2. **FeedConfig objects** that define how each entity type behaves
3. **Generic signal handlers** that work for all registered entity types
4. **Automatic feed entry creation, updates, and deletion**

## Benefits

- **Reduced code duplication**: No more copy-paste signal handlers
- **Consistent behavior**: All entity types follow the same patterns
- **Easier maintenance**: Changes to feed logic only need to be made in one place
- **Better testability**: Generic system is easier to test comprehensively
- **Extensibility**: Adding new entity types requires minimal code

## Architecture

### Core Components

1. **FeedManager** (`feed/feed_manager.py`): Central manager for all feed operations
2. **FeedConfig** (`feed/feed_manager.py`): Configuration class that defines entity behavior
3. **Entity Configurations** (`feed/feed_configs.py`): Specific configs for each entity type
4. **Signal Setup** (`feed/feed_configs.py`): M2M signal handlers and app initialization

### How It Works

1. **Registration**: Entity types are registered with the FeedManager using FeedConfig objects
2. **Signal Handling**: Generic signal handlers catch model changes for registered entities
3. **Feed Operations**: The FeedManager performs appropriate feed operations based on the entity's configuration
4. **Task Execution**: Actual feed entry creation/deletion happens via Celery tasks (existing)

## Adding New Entity Types

To add a new entity type to the feed system:

### 1. Create a FeedConfig

```python
from feed.feed_manager import FeedConfig, register_feed_entity
from feed.models import FeedEntry

# In feed/feed_configs.py
def get_my_entity_unified_document(instance):
    return instance.unified_document

def get_my_entity_hub_ids(instance):
    return list(instance.unified_document.hubs.values_list("id", flat=True))

def get_my_entity_user(instance):
    return instance.created_by

# Register the entity
register_feed_entity(FeedConfig(
    model_class=MyEntity,
    feed_actions=[FeedEntry.PUBLISH],
    get_unified_document=get_my_entity_unified_document,
    get_hub_ids=get_my_entity_hub_ids,
    get_user=get_my_entity_user,
    create_on_save=True,
    delete_on_remove=True,
    update_related_metrics=False,
))
```

### 2. Call the Registration

Add the registration to `register_all_feed_entities()` in `feed/feed_configs.py`:

```python
def register_all_feed_entities():
    # ... existing registrations ...

    # New entity registration
    from myapp.models import MyEntity
    register_feed_entity(FeedConfig(
        # ... configuration as above ...
    ))
```

### 3. That's It!

The entity will now automatically:
- Create feed entries when instances are created
- Delete feed entries when instances are removed
- Handle hub association changes
- Update metrics for related entities (if configured)

## FeedConfig Options

### Required Fields

- **model_class**: The Django model class
- **feed_actions**: List of actions that create feed entries (e.g., `[FeedEntry.PUBLISH]`)
- **get_unified_document**: Function to get unified document from instance
- **get_hub_ids**: Function to get hub IDs from instance

### Optional Fields

- **get_user**: Function to get the user who performed the action
- **get_action_date**: Function to get custom action date (defaults to created_date)
- **create_on_save**: Whether to create feed entries when entity is created (default: True)
- **delete_on_remove**: Whether to delete feed entries when entity is removed (default: True)
- **update_related_metrics**: Whether to update metrics for related entities (default: False)
- **get_related_entities**: Function to get entities that need metric updates

### Helper Functions

The system provides common helper functions in `feed/feed_manager.py`:

- `get_unified_document_default(instance)`: Gets `instance.unified_document`
- `get_hub_ids_from_unified_document(instance)`: Gets hub IDs from unified document
- `get_user_created_by(instance)`: Gets `instance.created_by`
- `get_user_uploaded_by(instance)`: Gets `instance.uploaded_by`

## Examples

### Simple Entity (like Posts)

```python
register_feed_entity(FeedConfig(
    model_class=ResearchhubPost,
    feed_actions=[FeedEntry.PUBLISH],
    get_unified_document=get_unified_document_default,
    get_hub_ids=get_hub_ids_from_unified_document,
    get_user=get_user_created_by,
))
```

### Complex Entity (like Comments with Metric Updates)

```python
def get_comment_related_entities(comment):
    entities = []
    # Update parent document metrics
    if comment.unified_document:
        document = comment.unified_document.get_document()
        if document:
            entities.append(document)
    # Update parent comment metrics
    if comment.parent:
        entities.append(comment.parent)
    return entities

register_feed_entity(FeedConfig(
    model_class=RhCommentModel,
    feed_actions=[FeedEntry.PUBLISH],
    get_unified_document=get_comment_unified_document,
    get_hub_ids=get_hub_ids_from_unified_document,
    get_user=get_user_created_by,
    update_related_metrics=True,
    get_related_entities=get_comment_related_entities,
))
```

### Entity with Custom Action Date (like Papers)

```python
def get_paper_action_date(paper):
    return paper.paper_publish_date or paper.created_date

register_feed_entity(FeedConfig(
    model_class=Paper,
    feed_actions=[FeedEntry.PUBLISH],
    get_unified_document=get_unified_document_default,
    get_hub_ids=get_hub_ids_from_unified_document,
    get_user=get_user_uploaded_by,
    get_action_date=get_paper_action_date,
))
```

## Migrating from Old System

### For Existing Signal Files

The old signal files have been updated to indicate they're legacy:

- `feed/signals/post_signals.py` - Now legacy
- `feed/signals/comment_signals.py` - Now legacy
- `feed/signals/document_signals.py` - Partially legacy (unified document removal still handled here)

### Testing Migration

1. **Verify Registration**: Ensure your entity types are registered in `feed/feed_configs.py`
2. **Test Signal Handling**: Create/update/delete entity instances and verify feed entries are created/updated/deleted
3. **Test Hub Changes**: Add/remove entities from hubs and verify feed entries are updated
4. **Test Metric Updates**: For entities with `update_related_metrics=True`, verify related entities get metric updates

### Rollback Plan

If issues arise, you can temporarily disable the generic system by:

1. Commenting out the registration calls in `feed/apps.py`
2. Re-enabling the old signal handlers in the individual signal files
3. Investigating and fixing the issue
4. Re-enabling the generic system

## Advanced Usage

### Custom Feed Actions

You can define custom feed actions by adding them to your FeedConfig:

```python
register_feed_entity(FeedConfig(
    model_class=MyEntity,
    feed_actions=[FeedEntry.PUBLISH, FeedEntry.OPEN],  # Multiple actions
    # ... other config ...
))
```

### Conditional Feed Entry Creation

You can add logic to your configuration functions to conditionally create feed entries:

```python
def get_my_entity_hub_ids(instance):
    # Only create feed entries for published instances
    if not instance.is_published:
        return []
    return list(instance.unified_document.hubs.values_list("id", flat=True))
```

### Manual Feed Operations

You can also manually trigger feed operations:

```python
from feed.feed_manager import feed_manager

# Refresh all feed entries for an entity
feed_manager.refresh_entity_feed_entries(my_instance)

# Handle hub changes manually
feed_manager.handle_hubs_changed(my_instance, "post_add", {hub_id})
```

## Troubleshooting

### Common Issues

1. **Entity not creating feed entries**: Check if it's registered in `feed/feed_configs.py`
2. **Wrong hub associations**: Verify the `get_hub_ids` function returns correct hub IDs
3. **Missing metrics updates**: Ensure `update_related_metrics=True` and `get_related_entities` is properly defined
4. **Signal conflicts**: Make sure old signal handlers are disabled/removed

### Debugging

Enable debug logging to see what the feed manager is doing:

```python
import logging
logging.getLogger('feed.feed_manager').setLevel(logging.DEBUG)
```

### Performance

The generic system uses the same Celery tasks as the old system, so performance should be equivalent or better due to reduced code paths.

## Future Enhancements

Potential improvements to the system:

1. **Configuration validation**: Validate FeedConfig objects at registration time
2. **Batch operations**: Optimize for bulk entity operations
3. **Feed entry priorities**: Allow different priorities for different entity types
4. **Conditional feed actions**: More sophisticated logic for when to create feed entries
5. **Feed entry templates**: Standardized templates for feed entry content/metrics
