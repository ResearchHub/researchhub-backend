"""
User interaction event types for tracking and ML processing via Personalize.
"""

UPVOTE = "UPVOTE"
FEED_ITEM_CLICK = "FEED_ITEM_CLICK"
PAGE_VIEW = "PAGE_VIEW"

EVENT_CHOICES = [
    (UPVOTE, UPVOTE),
    (FEED_ITEM_CLICK, FEED_ITEM_CLICK),
    (PAGE_VIEW, PAGE_VIEW),
]

EVENT_WEIGHTS = {
    UPVOTE: 3.0,
    FEED_ITEM_CLICK: 2.0,
    PAGE_VIEW: 1.0,
}
