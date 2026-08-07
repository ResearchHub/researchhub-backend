"""Notebook note tools for the agent core.

``NoteToolset`` lets an agent read and edit Tiptap notes on behalf of a
specific user. Reads hand the model the raw Tiptap/ProseMirror document JSON
plus a version id; edits are full-document replaces guarded by that version id
(optimistic concurrency), and each edit appends a new ``NoteContent`` version
rather than mutating in place, so any agent edit is recoverable from history.

Permission checks mirror the HTTP layer on the note's unified document:
reads use the ``HasAccessPermission`` predicate (any non-NO_ACCESS
permission), writes the stricter ``HasEditingPermission`` one (editor or
admin). A toolset built for a single-note surface can additionally be
scoped with ``note_ids``; notes outside the scope get the same not-found
error as inaccessible ones.
"""

import logging
from collections.abc import Collection

from django.db import transaction

from note.related_models.note_model import Note
from note.services.note_content_service import NoteContentService
from research_ai.services.agent import Tool, Toolset
from researchhub_document.registered_report_note_metadata import parse_note_json

logger = logging.getLogger(__name__)

READ_NOTE = "read_note"
EDIT_NOTE = "edit_note"


class NoteToolset:
    """Note read/edit tools acting with ``user``'s permissions.

    ``note_ids``, when given, restricts every tool to those notes regardless
    of what else the user could access.

    Best-effort contract: handlers never raise; failures come back to the
    model as ``{"error": ...}`` so a bad note id or a stale edit is a turn
    the agent can recover from, not an aborted run.
    """

    def __init__(
        self,
        *,
        user,
        service: NoteContentService | None = None,
        note_ids: Collection[int] | None = None,
    ):
        self._user = user
        self._service = service or NoteContentService()
        self._note_ids = None if note_ids is None else frozenset(note_ids)

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=READ_NOTE,
                description=(
                    "Read a ResearchHub notebook note. Returns the note title, "
                    "the current Tiptap/ProseMirror document JSON as `content`, "
                    "and the `version_id` that edit_note requires. For legacy "
                    "notes `content` may be null; `plain_text` is included then "
                    "as a read-only fallback."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "integer",
                            "description": "Id of the note to read.",
                        },
                    },
                    "required": ["note_id"],
                },
                handler=self._read_note,
            ),
            Tool(
                name=EDIT_NOTE,
                description=(
                    "Replace a note's content with a complete Tiptap document "
                    '(a JSON object like {"type": "doc", "content": [...]}). '
                    "Always call read_note first and pass the version_id you "
                    "read as expected_version_id; the edit is rejected if the "
                    "note changed since. Each edit is saved as a new version, "
                    "so prior content is kept as history."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "integer",
                            "description": "Id of the note to edit.",
                        },
                        "expected_version_id": {
                            "type": ["integer", "null"],
                            "description": (
                                "version_id from read_note. Pass null only if "
                                "read_note reported no version."
                            ),
                        },
                        "content": {
                            "type": "object",
                            "description": (
                                "Complete replacement Tiptap document, including "
                                "unchanged parts."
                            ),
                        },
                    },
                    "required": ["note_id", "expected_version_id", "content"],
                },
                handler=self._edit_note,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def _read_note(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}
        latest = note.latest_version
        # Stored JSON may be a JSON-encoded string rather than a dict;
        # normalize so `content` always matches the shape edit_note accepts.
        content = parse_note_json(latest.json) if latest else None
        result = {
            "note_id": note.id,
            "title": note.title,
            "version_id": latest.id if latest else None,
            "content": content,
        }
        if latest and content is None:
            result["plain_text"] = latest.plain_text
        return result

    def _edit_note(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}

        permissions = note.permissions
        if not (
            permissions.has_admin_user(self._user)
            or permissions.has_editor_user(self._user)
        ):
            return {"error": f"no edit permission on note {note.id}"}

        expected = input.get("expected_version_id")
        try:
            with transaction.atomic():
                # Lock the note row so the version check and the append are
                # one atomic step; a concurrent edit blocks here and then
                # sees the new latest_version_id (-> stale error) on entry.
                locked = Note.objects.select_for_update().get(id=note.id)
                if locked.latest_version_id != expected:
                    return {
                        "error": (
                            f"stale version: note {locked.id} is at version "
                            f"{locked.latest_version_id}, expected {expected}; "
                            "call read_note again and re-apply your edit"
                        )
                    }
                version = self._service.create_version(locked, input.get("content"))
        except (ValueError, Note.DoesNotExist) as exc:
            return {"error": str(exc)}
        return {"note_id": note.id, "version_id": version.id, "saved": True}

    def _get_readable_note(self, note_id) -> Note | None:
        """The note, or None when it does not exist or ``user`` cannot view it."""
        if self._user is None or getattr(self._user, "is_anonymous", False):
            return None
        try:
            # Same visibility rule as NoteViewSet: soft-deleted notes (removed
            # unified document) do not exist as far as the tools are concerned.
            note = Note.objects.get(id=note_id, unified_document__is_removed=False)
        except (Note.DoesNotExist, ValueError, TypeError):
            return None
        # Compare on the fetched id, not the raw input: the id is canonical
        # after the lookup, while the input may arrive as a string.
        if self._note_ids is not None and note.id not in self._note_ids:
            return None
        # Same predicate as HasAccessPermission: any non-NO_ACCESS permission
        # (user- or org-level) makes the note readable.
        if not note.permissions.has_user(self._user):
            return None
        return note
