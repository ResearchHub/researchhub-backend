"""
Signal handlers for Review model.

NOTE: This file is now legacy. The review signal handling is done through
the generic feed management system in feed.feed_manager and feed.feed_configs.

The generic system automatically handles:
- Creating feed entries when reviews are created
- Deleting feed entries when reviews are removed
- Updating metrics for related entities
- Hub association changes

To modify review feed behavior, update the Review configuration
in feed.feed_configs.py instead of modifying this file.
"""

# Legacy code kept for reference but no longer active
# All functionality moved to feed.feed_manager and feed.feed_configs

import warnings


def handle_review_created_or_updated(sender, instance, created, **kwargs):
    """
    DEPRECATED: This function is no longer used.

    Review feed entry updates are now handled automatically by the generic
    feed management system. See feed.feed_manager and feed.feed_configs.
    """
    warnings.warn(
        "handle_review_created_or_updated is deprecated. "
        "Review feed handling is now done by the generic feed management system.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Do nothing - the generic system handles this automatically
