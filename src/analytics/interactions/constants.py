# Event Types
PAGE_VIEW = "[Amplitude] Page Viewed"
FEED_ITEM_CLICKED = "feed_item_clicked"
ITEM_UPVOTED = "ITEM_UPVOTED"

# Event Weights (values for Personalize)
# These values represent the importance/weight of each event type
EVENT_WEIGHTS = {
    ITEM_UPVOTED: 1.0,
    PAGE_VIEW: 1.0,
    FEED_ITEM_CLICKED: 1.5,
}

# Mapping from Amplitude event types (lowercase) to database enum values (uppercase)
AMPLITUDE_TO_DB_EVENT_MAP = {
    "feed_item_clicked": "FEED_ITEM_CLICK",
    "page_viewed": "PAGE_VIEW",
}
