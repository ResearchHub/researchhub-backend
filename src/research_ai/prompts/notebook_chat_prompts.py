"""Prompt builder for the notebook chat assistant.

The system prompt pins the agent to one note (id + title) and states the
tool contract: research via list/detail OpenAlex and web tools, plus exactly one
note-editing workflow selected from the note's current storage shape. The user
prompt is the user's chat message verbatim, so there is no user-prompt builder.
"""

from research_ai.prompts._loader import load_template
from research_ai.services.note_tools import LEGACY_NOTE_MODE, SECTION_NOTE_MODE

_SECTION_EDITING_SUMMARY = (
    "inspect its outline, read only the relevant section(s), apply the change, "
    "and save each changed section."
)
_SECTION_EDITING_RULES = """1. Always call get_note_outline first, even if you
   edited recently: the user may have changed the note since. Use its section
   ids to call read_note_section only for content needed by the request.
2. Use replace_note_section. Send only the replacement top-level Tiptap blocks
   for that section, including its heading. The server preserves every unread
   section. For a document-wide restructure, update the required sections one
   at a time; full-document tools are intentionally unavailable.
3. Make the edit the user asked for -- no more. Match the note's existing tone,
   structure, and formatting. When adding researched material, attribute it in
   the text (authors, year, venue) so the user can verify it.
4. If an edit is rejected as stale, fetch the outline and relevant section
   again and re-apply your change to the newer version.
5. If the user's request is ambiguous or destructive (for example, deleting a
   large section), state your understanding in your reply and make the
   conservative edit rather than guessing broadly."""

_LEGACY_EDITING_SUMMARY = (
    "use the legacy full-note tools. This note does not have section-addressable "
    "Tiptap content."
)
_LEGACY_EDITING_RULES = """1. Always call read_note first, even if you edited
   recently: the user may have changed the note since. Pass its version_id to
   edit_note.
2. edit_note requires a complete replacement Tiptap document. Preserve all
   content outside the requested change. This full-document workflow is
   available only because this note has legacy content.
3. Make the edit the user asked for -- no more. Match the note's existing tone,
   structure, and formatting. When adding researched material, attribute it in
   the text (authors, year, venue) so the user can verify it.
4. If an edit is rejected as stale, call read_note again and re-apply your
   change to the newer version.
5. If the user's request is ambiguous or destructive (for example, deleting a
   large section), state your understanding in your reply and make the
   conservative edit rather than guessing broadly."""


def build_notebook_chat_system_prompt(note, *, note_mode: str) -> str:
    """The system prompt for a conversation attached to ``note``."""
    if note_mode == SECTION_NOTE_MODE:
        editing_summary = _SECTION_EDITING_SUMMARY
        editing_rules = _SECTION_EDITING_RULES
    elif note_mode == LEGACY_NOTE_MODE:
        editing_summary = _LEGACY_EDITING_SUMMARY
        editing_rules = _LEGACY_EDITING_RULES
    else:
        raise ValueError(f"unsupported note tool mode: {note_mode}")
    template = load_template("notebook_chat_system.txt")
    return (
        template.replace("{{NOTE_ID}}", str(note.id))
        .replace("{{NOTE_TITLE}}", str(note.title or "Untitled"))
        .replace("{{NOTE_EDITING_SUMMARY}}", editing_summary)
        .replace("{{NOTE_EDITING_RULES}}", editing_rules)
    )
