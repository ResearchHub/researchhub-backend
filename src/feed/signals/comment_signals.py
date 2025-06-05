"""
Signal handlers for Comment model.

NOTE: This file is now legacy. The comment signal handling is done through
the generic feed management system in feed.feed_manager and feed.feed_configs.

The generic system automatically handles:
- Creating feed entries when comments are created
- Deleting feed entries when comments are removed
- Updating metrics for related entities (parent document, parent comment)
- Hub association changes

To modify comment feed behavior, update the RhCommentModel configuration
in feed.feed_configs.py instead of modifying this file.
"""

# Legacy code kept for reference but no longer active
# All functionality moved to feed.feed_manager and feed.feed_configs
