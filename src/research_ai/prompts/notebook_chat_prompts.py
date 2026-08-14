"""Prompt builder for the notebook chat assistant.

The system prompt pins the agent to one note (id + title) and states the
tool contract: research via OpenAlex/web tools, note edits via read_note /
edit_note with full-document replaces. The user prompt is the user's chat
message verbatim, so there is no user-prompt builder here.
"""

from note.models import Note
from research_ai.prompts._loader import load_template


def build_notebook_chat_system_prompt(note: Note) -> str:
    """Build the system prompt for a conversation attached to ``note``."""
    template = load_template("notebook_chat_system.txt")
    grant_context = ""
    if note.selected_grant_id is not None:
        grant = note.selected_grant
        grant_context = (
            "## Selected funding opportunity\n\n"
            f"Grant ID: {grant.id}\n\n"
            f"RFP context:\n{grant.get_llm_context_text()}"
        )
    return (
        template.replace("{{NOTE_ID}}", str(note.id))
        .replace("{{NOTE_TITLE}}", str(note.title or "Untitled"))
        .replace("{{GRANT_CONTEXT}}", grant_context)
    )
