"""
Views for the feed app.

Note: This file is being maintained for backward compatibility.
New views should be added to the views/ directory.
"""

from .views.feed_view import FeedViewSet
from .views.funding_feed_view import FundingFeedViewSet

__all__ = ["FeedViewSet", "FundingFeedViewSet"]
