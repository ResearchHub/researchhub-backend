"""
Signal handlers for Bounty model.

NOTE: This file is now legacy. The bounty signal handling is done through
the generic feed management system in feed.feed_manager and feed.feed_configs.

The generic system automatically handles:
- Creating feed entries when bounties are created
- Deleting feed entries when bounties are removed
- Updating metrics for related entities
- Hub association changes

To modify bounty feed behavior, update the Bounty configuration
in feed.feed_configs.py instead of modifying this file.
"""

# Legacy code kept for reference but no longer active
# All functionality moved to feed.feed_manager and feed.feed_configs

import warnings


def handle_bounty_delete_update_feed_entries(sender, instance, **kwargs):
    """
    DEPRECATED: This function is no longer used.

    Bounty feed entry updates are now handled automatically by the generic
    feed management system. See feed.feed_manager and feed.feed_configs.
    """
    warnings.warn(
        "handle_bounty_delete_update_feed_entries is deprecated. "
        "Bounty feed handling is now done by the generic feed management system.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Do nothing - the generic system handles this automatically
