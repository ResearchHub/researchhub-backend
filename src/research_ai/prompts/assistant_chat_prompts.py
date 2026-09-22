"""Prompt builder for the note-less research assistant chat.

The system prompt states that the chat is attached to no document, says what
the user opened it to do when that is known, lists the notes this conversation
has created so far (so later turns know their ids), and gives the same research
and note-editing tool contract as the notebook assistant plus ``create_note``,
narrowed to the note type the user's purpose calls for.
"""

from collections.abc import Iterable

from research_ai.models import AgentConversation
from research_ai.prompts._loader import load_template

_NO_NOTES = (
    "This chat has not created any notes yet. You have no access to the "
    "user's other notes."
)
_NOTES_HEADER = (
    "This chat has created the notes below; they are the only notes you can "
    "read or edit. Use these ids with read_note and edit_note."
)

_PURPOSE = {
    AgentConversation.Intent.FUND: (
        "## Purpose\n\n"
        "The user opened this chat to fund research: they are a funder shaping "
        "a Request for Proposals (RFP) that researchers will answer. Help them "
        "define what they want funded, who should apply and what a strong "
        "application looks like."
    ),
    AgentConversation.Intent.NEED_FUNDING: (
        "## Purpose\n\n"
        "The user opened this chat to get their research funded: they are a "
        "researcher preparing a proposal. Help them shape hypotheses, methods, "
        "a budget and the case for funding, grounded in their own record."
    ),
}
_SELECTED_GRANT = (
    'They are applying to the Request for Proposals "{title}" (grant {grant_id}). '
    "A proposal this chat creates answers it: call get_grant_details on it "
    "before drafting, and let its brief and requirements shape the draft."
)

_DOCUMENT_TYPES = {
    AgentConversation.Intent.FUND: (
        "Every note you create here is a GRANT: the RFP itself. Use "
        "document_type GRANT; no other type can be created in this chat. "
        "Answer other requests in chat rather than creating a document."
    ),
    AgentConversation.Intent.NEED_FUNDING: (
        "Every note you create here is a PREREGISTRATION: the research "
        "proposal or funding application. Use document_type PREREGISTRATION; "
        "no other type can be created in this chat. Answer other requests in "
        "chat rather than creating a document."
    ),
}
_DOCUMENT_TYPES_ANY = (
    "Choose document_type based on what you are writing: GRANT for an RFP or "
    "call for proposals, PREREGISTRATION for a research proposal or funding "
    "application (including a response to an RFP). Only these two document "
    "types can be created. Answer other requests in chat; do not misclassify "
    "them to create a document."
)


def build_assistant_chat_system_prompt(
    notes: Iterable, *, intent: str = "", selected_grant=None
) -> str:
    """The system prompt for a conversation with ``notes`` created so far,
    opened with ``intent`` and, when seeking funding, to answer
    ``selected_grant``."""
    template = load_template("assistant_chat_system.txt")
    lines = [f'- note {note.id} ("{note.title or "Untitled"}")' for note in notes]
    notes_section = f"{_NOTES_HEADER}\n\n" + "\n".join(lines) if lines else _NO_NOTES

    purpose = _PURPOSE.get(intent, "")
    if purpose and selected_grant is not None:
        purpose += "\n\n" + _SELECTED_GRANT.format(
            title=selected_grant.short_title or "Untitled", grant_id=selected_grant.id
        )

    return (
        template.replace("{{PURPOSE_SECTION}}", purpose)
        .replace("{{NOTES_SECTION}}", notes_section)
        .replace("{{DOCUMENT_TYPES}}", _DOCUMENT_TYPES.get(intent, _DOCUMENT_TYPES_ANY))
    )
