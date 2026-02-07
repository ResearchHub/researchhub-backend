# Chat request action values
class ChatAction:
    """Constants for the chat request action field."""

    START = "start"
    RESUME = "resume"
    MESSAGE = "message"

    CHOICES = [START, RESUME, MESSAGE]


# Field state status values
class FieldStatus:
    """Constants for field state status values."""

    EMPTY = "empty"
    AI_SUGGESTED = "ai_suggested"
    COMPLETE = "complete"

    CHOICES = [EMPTY, AI_SUGGESTED, COMPLETE]


# Initial field state definitions per role
# Note: "description" (the document body) is NOT a form field — it's managed
# via the rich editor and AI conversation. Only form fields are tracked here.
RESEARCHER_FIELDS = [
    "title",
    "authors",
    "hubs",
]

FUNDER_FIELDS = [
    "title",
    "grant_amount",
    "grant_end_date",
    "grant_organization",
    "hubs",
    "grant_contacts",
]

RESEARCHER_REQUIRED = {"title", "hubs"}
FUNDER_REQUIRED = {"title", "grant_amount", "hubs"}
