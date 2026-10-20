"""Score chat messages for spam and off-purpose use, and record the verdict."""

import logging

from django.conf import settings

from note.related_models.note_model import Note
from research_ai.models import AgentConversationMessage, AgentMessageScreening
from research_ai.services.message_screening.jev_client import DecisionError, JevClient

logger = logging.getLogger(__name__)

# Starting point from a handful of probes; tune on the recorded scores.
FLAG_THRESHOLD = 0.8
# Chat messages go up to 20,000 characters; the intent shows well before that.
MAX_MESSAGE_CHARS = 8_000
# Intent can surface only in a follow-up ("i mean for social media content").
EARLIER_MESSAGES = 3
EARLIER_MESSAGE_CHARS = 1_000
# Spam often arrives as a file or sits in the note, with little typed text.
NOTE_TEXT_CHARS = 2_000
FILES = 5
FILE_TEXT_CHARS = 2_000

QUESTIONS = {
    "promotional": {
        "type": "noul",
        "instructions": (
            "Judging the latest message together with the earlier messages, "
            "the note, and the attached files: is the user asking for "
            "marketing or promotional material, such as ads, product or brand "
            "copy, affiliate content, SEO articles or backlinks, social media "
            "content, sales pages, or product reviews or buying guides?"
        ),
        "criteria": {
            "true": (
                "The request is mainly to promote, sell, or rank a product, "
                "service, brand, or website."
            ),
            "false": (
                "The request is not promotional, even if it mentions a "
                "company, product, or funder."
            ),
        },
    },
    "off_purpose": {
        "type": "noul",
        "instructions": (
            "ResearchHub's assistant helps with scientific research: "
            "literature, research proposals, funding opportunities (RFPs), "
            "study design, and notes about research. Judging the latest "
            "message together with the earlier messages, the note, and the "
            "attached files: is the user using it for commercial or "
            "non-research work instead?"
        ),
        "criteria": {
            "true": (
                "The work is commercial or not research: websites, marketing, "
                "business or consumer content, or general chat."
            ),
            "false": (
                "The work is research, a research proposal, an RFP, a grant, a "
                "paper, or the user's research note, even if short or vague. "
                "Unconventional, speculative, or fringe science is still "
                "research."
            ),
        },
    },
}


class MessageScreeningService:
    """Records a Jev verdict per user message; the verdict changes nothing yet."""

    def __init__(self, client: JevClient | None = None):
        self.client = (
            JevClient.from_settings(settings.RESEARCH_AI_MESSAGE_SCREENING)
            if client is None
            else client
        )

    def screen(
        self, message: AgentConversationMessage, *, note: Note | None = None
    ) -> AgentMessageScreening | None:
        """The message's screening, made on first call; ``None`` when disabled."""
        if self.client is None:
            return None
        # A retried turn reuses its message, and its verdict.
        existing = AgentMessageScreening.objects.filter(message=message).first()
        if existing is not None:
            return existing
        try:
            decision = self.client.decide(message_state(message, note), QUESTIONS)
        except DecisionError as exc:
            logger.warning("could not screen chat message %s: %s", message.id, exc)
            return AgentMessageScreening.objects.create(
                message=message, model=self.client.model, error=str(exc)
            )
        promotional = decision.answers["promotional"]
        off_purpose = decision.answers["off_purpose"]
        return AgentMessageScreening.objects.create(
            message=message,
            model=decision.model,
            promotional=promotional,
            off_purpose=off_purpose,
            flagged=max(promotional, off_purpose) >= FLAG_THRESHOLD,
            cost_microusd=decision.cost_microusd,
        )


def message_state(message: AgentConversationMessage, note: Note | None) -> dict:
    """What Jev judges a chat message by: it, the user's earlier messages, the
    note, and the attached files.
    """
    state = {
        "workflow": message.conversation.workflow,
        "message": message.content[:MAX_MESSAGE_CHARS],
    }
    earlier = list(
        AgentConversationMessage.objects.filter(
            conversation_id=message.conversation_id,
            role=AgentConversationMessage.Role.USER,
            is_active=True,
            sequence__lt=message.sequence,
        )
        .order_by("-sequence")
        .values_list("content", flat=True)[:EARLIER_MESSAGES]
    )
    if earlier:
        state["earlier_messages"] = [
            content[:EARLIER_MESSAGE_CHARS] for content in reversed(earlier)
        ]
    if note is not None:
        version = note.latest_version
        state["note"] = {
            "title": note.title,
            "type": note.document_type,
            "text": ((version and version.plain_text) or "")[:NOTE_TEXT_CHARS],
        }
    files = message.attachments.order_by("id").values_list("filename", "text")
    attached = [
        {"name": name, "text": text[:FILE_TEXT_CHARS]} for name, text in files[:FILES]
    ]
    if attached:
        state["attached_files"] = attached
    return state
