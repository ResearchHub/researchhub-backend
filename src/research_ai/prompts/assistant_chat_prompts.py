"""Prompt builders for the note-less research assistant chat.

The system prompt states that the chat is attached to no document and gives
the same research and note-editing tool contract as the notebook assistant
plus ``create_note``. It is the same on every turn: the notes this
conversation has created are listed in a notice opening each turn's prompt
instead, so creating or renaming one does not change the prompt the provider
caches.
"""

from collections.abc import Iterable

from research_ai.prompts._loader import load_template


def build_assistant_chat_system_prompt() -> str:
    """The system prompt for every turn of an assistant conversation."""
    return load_template("assistant_chat_system.txt")


def build_created_notes_notice(notes: Iterable) -> str | None:
    """The notice naming the notes a conversation has created; ``None`` for none."""
    listed = "; ".join(
        f'note {note.id} ("{note.title or "Untitled"}")' for note in notes
    )
    if not listed:
        return None
    return (
        "[Notice from the system, not the user: this chat has created these "
        f"notes, the only ones you can read or edit: {listed}.]"
    )
