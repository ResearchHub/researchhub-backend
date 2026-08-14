"""Prompt builder for the notebook chat assistant.

The system prompt pins the agent to one note (id + title) and states the
tool contract: research via OpenAlex/web tools, note edits via read_note /
edit_note with full-document replaces. The user prompt is the user's chat
message verbatim, so there is no user-prompt builder here.
"""

from research_ai.prompts._loader import load_template


def build_notebook_chat_system_prompt(note) -> str:
    """The system prompt for a conversation attached to ``note``."""
    template = load_template("notebook_chat_system.txt")
    return template.replace("{{NOTE_ID}}", str(note.id)).replace(
        "{{NOTE_TITLE}}", str(note.title or "Untitled")
    )
