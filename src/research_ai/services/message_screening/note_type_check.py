"""Notice when a chat's RFP or proposal note looks like it has the wrong type.

People put their own study into an RFP note and ask for money, or write a call
for applicants inside a proposal. Jev judges the message with its note; when it
is confident, the turn tells the agent to offer a switch, once per chat.
"""

import logging

from django.conf import settings

from note.related_models.note_model import Note
from research_ai.models import (
    AgentConversationMessage,
    AgentExecution,
    AgentNoteTypeCheck,
)
from research_ai.services.message_screening.jev_client import DecisionError, JevClient
from research_ai.services.message_screening.service import message_state
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

logger = logging.getLogger(__name__)

# Made-up probes scored 0.88-0.95 for a wrong type and at most 0.20 otherwise.
SUGGEST_THRESHOLD = 0.8

_TERMS = (
    "On ResearchHub, an RFP (request for proposals) is a funding call: a "
    "funder describes the research they will pay for and invites other "
    "researchers to apply. A proposal is a researcher's plan for a study they "
    "will run themselves and want funded."
)

# Note type -> (question name, the question asked about a note of that type).
QUESTIONS = {
    GRANT: (
        "proposal_in_rfp",
        {
            "type": "noul",
            "instructions": (
                f"{_TERMS} The note is an RFP draft. Judging the latest message "
                "together with the earlier messages, the note, and the attached "
                "files: is the user writing a proposal instead, describing a "
                "study they or their team will run, or asking for funding for "
                "their own work?"
            ),
            "criteria": {
                "true": (
                    "The user describes research they or their own team will "
                    "carry out, or wants money for their own project."
                ),
                "false": (
                    "The user is writing a call that invites other researchers "
                    "to apply, is only researching a topic, or what they want "
                    "is unclear."
                ),
            },
        },
    ),
    PREREGISTRATION: (
        "rfp_in_proposal",
        {
            "type": "noul",
            "instructions": (
                f"{_TERMS} The note is a proposal draft. Judging the latest "
                "message together with the earlier messages, the note, and the "
                "attached files: is the user writing an RFP instead, a call "
                "that invites other researchers to apply for funding the user "
                "or their organization will give?"
            ),
            "criteria": {
                "true": (
                    "The user offers funding and invites other researchers or "
                    "teams to apply for it."
                ),
                "false": (
                    "The user is planning, writing, or seeking funding for "
                    "their own study, applying to someone else's RFP, only "
                    "researching a topic, or what they want is unclear."
                ),
            },
        },
    ),
}
SUGGESTED_TYPE = {GRANT: PREREGISTRATION, PREREGISTRATION: GRANT}

_NOTICES = {
    GRANT: (
        "this note is an RFP, a funding call that invites other researchers to "
        "apply, but the user seems to be describing a study they will run "
        "themselves or asking for funding for their own work. That is a "
        "proposal. In a sentence or two, explain the difference and ask "
        "whether they want this note switched to a proposal"
    ),
    PREREGISTRATION: (
        "this note is a proposal, a researcher's plan for a study they will "
        "run themselves, but the user seems to be writing an RFP, a funding "
        "call that invites other researchers to apply for money they or their "
        "organization will give. In a sentence or two, explain the difference "
        "and ask whether they want this note switched to an RFP"
    ),
}


class NoteTypeCheckService:
    """Records a Jev verdict per user message on whether the note has the wrong type."""

    def __init__(self, client: JevClient | None = None):
        self.client = (
            JevClient.from_settings(settings.RESEARCH_AI_NOTE_TYPE_CHECK)
            if client is None
            else client
        )

    def check(
        self, message: AgentConversationMessage, note: Note | None
    ) -> AgentNoteTypeCheck | None:
        """The message's check, made on first call.

        ``None`` when checking is off, the note is neither an RFP nor a
        proposal, or the agent already offered a switch in this chat.
        """
        if self.client is None or note is None or note.document_type not in QUESTIONS:
            return None
        # A retried turn reuses its message, and its verdict.
        existing = AgentNoteTypeCheck.objects.filter(message=message).first()
        if existing is not None:
            return existing
        if _offered_before(message):
            return None
        name, question = QUESTIONS[note.document_type]
        check = AgentNoteTypeCheck(
            message=message,
            note_type=note.document_type,
            suggested_type=SUGGESTED_TYPE[note.document_type],
            model=self.client.model,
        )
        try:
            decision = self.client.decide(
                message_state(message, note), {name: question}
            )
        except DecisionError as exc:
            logger.warning(
                "could not check note type for message %s: %s", message.id, exc
            )
            check.error = str(exc)
        else:
            check.model = decision.model
            check.probability = decision.answers[name]
            check.suggested = check.probability >= SUGGEST_THRESHOLD
            check.cost_microusd = decision.cost_microusd
        check.save()
        return check


def switch_notice(check: AgentNoteTypeCheck | None, note: Note | None) -> str | None:
    """The turn's notice asking the agent to offer a switch, if it should."""
    if check is None or not check.suggested or note is None:
        return None
    # The user may have switched it themself before a retry.
    if note.document_type != check.note_type:
        return None
    return (
        "[Notice from the system, not the user: "
        + _NOTICES[check.note_type]
        + "; then help with their message as far as it does not depend on the "
        "note's type. change_note_type refuses during this turn: switch only "
        "after they say yes. Ask once: if they decline or do not answer, leave "
        "the type as it is and do not raise it again in this chat.]"
    )


def _offered_before(message: AgentConversationMessage) -> bool:
    """Whether an earlier turn in the chat told the agent to offer a switch."""
    return (
        AgentNoteTypeCheck.objects.filter(
            message__conversation_id=message.conversation_id,
            suggested=True,
            # A turn that failed never reached the user.
            message__triggered_executions__status=AgentExecution.Status.SUCCEEDED,
        )
        .exclude(message=message)
        .exists()
    )
