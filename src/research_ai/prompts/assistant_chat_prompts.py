"""Prompt builder for the note-less research assistant chat.

The system prompt states that the chat is attached to no document, lists the
notes this conversation has created so far (so later turns know their ids),
and gives the same research and note-editing tool contract as the notebook
assistant plus ``create_note``.
"""

from collections.abc import Iterable

from research_ai.prompts._loader import load_template

_NO_NOTES = (
    "This chat has not created any notes yet. You have no access to the "
    "user's other notes."
)
_NOTES_HEADER = (
    "This chat has created the notes below; they are the only notes you can "
    "read or edit. Use these ids with read_note and edit_note."
)


def build_assistant_chat_system_prompt(notes: Iterable) -> str:
    """The system prompt for a conversation with ``notes`` created so far."""
    template = load_template("assistant_chat_system.txt")
    lines = [f'- note {note.id} ("{note.title or "Untitled"}")' for note in notes]
    section = f"{_NOTES_HEADER}\n\n" + "\n".join(lines) if lines else _NO_NOTES
    return template.replace("{{NOTES_SECTION}}", section)
