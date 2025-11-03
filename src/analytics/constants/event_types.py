"""
User interaction event types for tracking and ML processing via Personalize.
"""

# Database event types
UPVOTE = "UPVOTE"
FEED_ITEM_CLICK = "FEED_ITEM_CLICK"
PAGE_VIEW = "PAGE_VIEW"

# Amplitude event types
FEED_ITEM_CLICKED = "feed_item_clicked"
PAGE_VIEWED = "work_document_viewed"

EVENT_CHOICES = [
    (UPVOTE, UPVOTE),
    (FEED_ITEM_CLICK, FEED_ITEM_CLICK),
    (PAGE_VIEW, PAGE_VIEW),
]

# Event Weights
EVENT_WEIGHTS = {
    UPVOTE: 3.0,
    FEED_ITEM_CLICK: 2.0,
    PAGE_VIEW: 1.0,
}

# Mapping from Amplitude event types to database enum values
AMPLITUDE_TO_DB_EVENT_MAP = {
    FEED_ITEM_CLICKED: FEED_ITEM_CLICK,
    PAGE_VIEWED: PAGE_VIEW,
}
