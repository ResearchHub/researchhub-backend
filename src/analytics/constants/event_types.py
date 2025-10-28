"""
User interaction event types for tracking and ML processing via Personalize.
"""

ITEM_UPVOTED = "UPVOTE"
FEED_ITEM_CLICK = "FEED_ITEM_CLICK"
PAGE_VIEW = "PAGE_VIEW"

EVENT_CHOICES = [
    (ITEM_UPVOTED, "UPVOTE"),
    (FEED_ITEM_CLICK, FEED_ITEM_CLICK),
    (PAGE_VIEW, PAGE_VIEW),
]
