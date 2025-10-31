"""
Constants for AWS Personalize item data export.

Defines field names, CSV headers, and data types matching the Avro schema.
"""

# CSV Field Names (matching Avro schema)
ITEM_ID = "ITEM_ID"
ITEM_TYPE = "ITEM_TYPE"
HUB_L1 = "HUB_L1"
HUB_L2 = "HUB_L2"
HUB_IDS = "HUB_IDS"
AUTHOR_IDS = "AUTHOR_IDS"
CREATION_TIMESTAMP = "CREATION_TIMESTAMP"
TEXT = "TEXT"
TITLE = "TITLE"
UPVOTE_SCORE = "UPVOTE_SCORE"
BLUESKY_COUNT_TOTAL = "BLUESKY_COUNT_TOTAL"
TWEET_COUNT_TOTAL = "TWEET_COUNT_TOTAL"
CITATION_COUNT_TOTAL = "CITATION_COUNT_TOTAL"
PEER_REVIEW_COUNT_TOTAL = "PEER_REVIEW_COUNT_TOTAL"
HAS_ACTIVE_BOUNTY = "HAS_ACTIVE_BOUNTY"
BOUNTY_HAS_SOLUTIONS = "BOUNTY_HAS_SOLUTIONS"
RFP_IS_OPEN = "RFP_IS_OPEN"
RFP_HAS_APPLICANTS = "RFP_HAS_APPLICANTS"
PROPOSAL_IS_OPEN = "PROPOSAL_IS_OPEN"
PROPOSAL_HAS_FUNDERS = "PROPOSAL_HAS_FUNDERS"

# Delimiter for list fields (HUB_IDS, AUTHOR_IDS)
DELIMITER = "|"

# Limits for list fields to prevent data bloat
MAX_AUTHOR_IDS = 3  # First, second, last
MAX_HUB_IDS = 20

# CSV Headers (in order for the CSV file)
CSV_HEADERS = [
    ITEM_ID,
    ITEM_TYPE,
    HUB_L1,
    HUB_L2,
    HUB_IDS,
    AUTHOR_IDS,
    CREATION_TIMESTAMP,
    TEXT,
    TITLE,
    UPVOTE_SCORE,
    BLUESKY_COUNT_TOTAL,
    TWEET_COUNT_TOTAL,
    CITATION_COUNT_TOTAL,
    PEER_REVIEW_COUNT_TOTAL,
    HAS_ACTIVE_BOUNTY,
    BOUNTY_HAS_SOLUTIONS,
    RFP_IS_OPEN,
    RFP_HAS_APPLICANTS,
    PROPOSAL_IS_OPEN,
    PROPOSAL_HAS_FUNDERS,
]

# Default values for each field
FIELD_DEFAULTS = {
    # String/ID fields (nullable)
    ITEM_ID: None,
    ITEM_TYPE: None,
    HUB_L1: None,
    HUB_L2: None,
    HUB_IDS: None,
    AUTHOR_IDS: None,
    CREATION_TIMESTAMP: None,
    TEXT: None,
    TITLE: None,
    # Integer fields (counts, scores)
    UPVOTE_SCORE: 0,
    BLUESKY_COUNT_TOTAL: 0,
    TWEET_COUNT_TOTAL: 0,
    CITATION_COUNT_TOTAL: 0,
    PEER_REVIEW_COUNT_TOTAL: 0,
    # Boolean fields (flags)
    HAS_ACTIVE_BOUNTY: False,
    BOUNTY_HAS_SOLUTIONS: False,
    RFP_IS_OPEN: False,
    RFP_HAS_APPLICANTS: False,
    PROPOSAL_IS_OPEN: False,
    PROPOSAL_HAS_FUNDERS: False,
}

# Document types to exclude from export
EXCLUDED_DOCUMENT_TYPES = ["NOTE", "HYPOTHESIS"]

# Document types to include in export
SUPPORTED_DOCUMENT_TYPES = [
    "GRANT",
    "PREREGISTRATION",
    "DISCUSSION",
    "QUESTION",
    "PAPER",
]

# Text field maximum length (to prevent CSV cell overflow)
MAX_TEXT_LENGTH = 10000

# ITEM_TYPE mapping for Personalize export
# Maps internal document_type to Personalize-friendly type names
ITEM_TYPE_MAPPING = {
    "PREREGISTRATION": "PROPOSAL",
    "GRANT": "RFP",
    "DISCUSSION": "POST",
    "QUESTION": "QUESTION",
    "PAPER": "PAPER",
}
