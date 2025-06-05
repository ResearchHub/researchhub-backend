"""
Signal handlers for ResearchhubPost model.

NOTE: This file is now legacy. The post signal handling is done through
the generic feed management system in feed.feed_manager and feed.feed_configs.

The generic system automatically handles:
- Creating feed entries when posts are created
- Deleting feed entries when posts are removed
- Updating metrics for related entities
- Hub association changes

To modify post feed behavior, update the ResearchhubPost configuration
in feed.feed_configs.py instead of modifying this file.
"""

# Legacy code kept for reference but no longer active
# All functionality moved to feed.feed_manager and feed.feed_configs

import warnings


def handle_post_create_feed_entry(sender, instance, **kwargs):
    """
    DEPRECATED: This function is no longer used.

    Post feed entry creation is now handled automatically by the generic
    feed management system. See feed.feed_manager and feed.feed_configs.
    """
    warnings.warn(
        "handle_post_create_feed_entry is deprecated. "
        "Post feed handling is now done by the generic feed management system.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Do nothing - the generic system handles this automatically
