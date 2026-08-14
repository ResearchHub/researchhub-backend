"""Notebook note tools for the agent core.

``NoteToolset`` lets an agent read and edit Tiptap notes on behalf of a
specific user. Structured notes expose only outline -> section read -> section
replace, so a small edit cannot round-trip an entire large document through the
model. Legacy notes expose only the full-document fallback pair. Every write is
guarded by a version id (optimistic concurrency) and appends a new
``NoteContent`` version rather than mutating in place, so any agent edit is
recoverable from history.

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

from note.related_models.note_model import Note, NoteContent
from note.services.note_content_service import NoteContentService, extract_plain_text
from research_ai.services.agent import Tool, Toolset
from researchhub_document.registered_report_note_metadata import parse_note_json

logger = logging.getLogger(__name__)

GET_NOTE_OUTLINE = "get_note_outline"
READ_NOTE_SECTION = "read_note_section"
REPLACE_NOTE_SECTION = "replace_note_section"
READ_NOTE = "read_note"
EDIT_NOTE = "edit_note"

SECTION_NOTE_MODE = "section"
LEGACY_NOTE_MODE = "legacy"
_NOTE_MODES = frozenset({SECTION_NOTE_MODE, LEGACY_NOTE_MODE})

_PREAMBLE_SECTION_ID = "preamble"
_BODY_SECTION_ID = "body"


def _document_blocks(document: dict) -> list[dict]:
    blocks = document.get("content")
    return blocks if isinstance(blocks, list) else []


def _structured_document(latest: NoteContent | None) -> dict | None:
    document = parse_note_json(latest.json) if latest else None
    if document is None or document.get("type") != "doc":
        return None
    blocks = document.get("content")
    if blocks is not None and not isinstance(blocks, list):
        return None
    return document


def note_tool_mode(note: Note) -> str:
    """Return the one note-tool mode this note can safely use."""
    return (
        SECTION_NOTE_MODE
        if _structured_document(note.latest_version) is not None
        else LEGACY_NOTE_MODE
    )


def _document_sections(document: dict) -> list[dict]:
    """Addressable heading-based ranges in a Tiptap document.

    Heading ids use their top-level block index. They are intentionally valid
    only for the version returned with the outline; the write-side version
    check prevents an old positional id from targeting changed content.
    """
    blocks = _document_blocks(document)
    headings = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type") != "heading":
            continue
        attrs = block.get("attrs") or {}
        try:
            level = int(attrs.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        headings.append(
            {
                "section_id": f"heading-{index}",
                "heading": extract_plain_text({"type": "doc", "content": [block]}),
                "level": level,
                "start": index,
            }
        )

    if not headings:
        return [
            {
                "section_id": _BODY_SECTION_ID,
                "heading": None,
                "level": 0,
                "start": 0,
                "end": len(blocks),
            }
        ]

    sections = []
    if headings[0]["start"] > 0:
        sections.append(
            {
                "section_id": _PREAMBLE_SECTION_ID,
                "heading": None,
                "level": 0,
                "start": 0,
                "end": headings[0]["start"],
            }
        )
    for position, heading in enumerate(headings):
        end = len(blocks)
        for following in headings[position + 1 :]:
            if following["level"] <= heading["level"]:
                end = following["start"]
                break
        sections.append({**heading, "end": end})
    return sections


def _section_view(section: dict) -> dict:
    return {
        "section_id": section["section_id"],
        "heading": section["heading"],
        "level": section["level"],
        "block_count": section["end"] - section["start"],
    }


def _find_section(document: dict, section_id: str) -> dict | None:
    return next(
        (
            section
            for section in _document_sections(document)
            if section["section_id"] == section_id
        ),
        None,
    )


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
        mode: str,
        service: NoteContentService | None = None,
        note_ids: Collection[int] | None = None,
    ):
        if mode not in _NOTE_MODES:
            raise ValueError(f"unsupported note tool mode: {mode}")
        self._user = user
        self._mode = mode
        self._service = service or NoteContentService()
        self._note_ids = None if note_ids is None else frozenset(note_ids)

    # -- tool construction ------------------------------------------------

    def build_tools(self) -> list[Tool]:
        if self._mode == LEGACY_NOTE_MODE:
            return self._legacy_tools()
        return self._section_tools()

    def _section_tools(self) -> list[Tool]:
        return [
            Tool(
                name=GET_NOTE_OUTLINE,
                description=(
                    "Get a compact heading outline for a ResearchHub note. "
                    "Returns addressable section ids and the current version_id. "
                    "Use this first, then read only the sections needed."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {
                            "type": "integer",
                            "description": "Id of the note to inspect.",
                        },
                    },
                    "required": ["note_id"],
                },
                handler=self._get_note_outline,
            ),
            Tool(
                name=READ_NOTE_SECTION,
                description=(
                    "Read one section returned by get_note_outline. Returns "
                    "only that section's Tiptap top-level blocks plus the "
                    "current version_id."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "integer"},
                        "section_id": {
                            "type": "string",
                            "description": "Exact section_id from get_note_outline.",
                        },
                    },
                    "required": ["note_id", "section_id"],
                },
                handler=self._read_note_section,
            ),
            Tool(
                name=REPLACE_NOTE_SECTION,
                description=(
                    "Replace one section with Tiptap top-level blocks. Read the "
                    "outline/section first and pass its version_id as "
                    "expected_version_id. Unread sections are preserved server-side."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": {"type": "integer"},
                        "section_id": {
                            "type": "string",
                            "description": "Exact section_id from get_note_outline.",
                        },
                        "expected_version_id": {"type": ["integer", "null"]},
                        "content": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": (
                                "Replacement top-level Tiptap blocks, including "
                                "the section heading when the section has one."
                            ),
                        },
                    },
                    "required": [
                        "note_id",
                        "section_id",
                        "expected_version_id",
                        "content",
                    ],
                },
                handler=self._replace_note_section,
            ),
        ]

    def _legacy_tools(self) -> list[Tool]:
        return [
            Tool(
                name=READ_NOTE,
                description=(
                    "Read an entire legacy ResearchHub notebook note. Returns "
                    "the note title, "
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
                    "Replace a legacy note's content with a complete Tiptap "
                    "document "
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

    def _get_note_outline(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}
        latest = note.latest_version
        document = _structured_document(latest)
        if document is None:
            return {"error": "structured note content is no longer available"}
        return {
            "note_id": note.id,
            "title": note.title,
            "version_id": latest.id if latest else None,
            "sections": [
                _section_view(section) for section in _document_sections(document)
            ],
        }

    def _read_note_section(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}
        latest = note.latest_version
        document = _structured_document(latest)
        if document is None:
            return {"error": "structured note content is no longer available"}
        section_id = str(input.get("section_id") or "")
        section = _find_section(document, section_id)
        if section is None:
            return {
                "error": (
                    f"section {section_id!r} not found; call get_note_outline again"
                )
            }
        blocks = _document_blocks(document)
        return {
            "note_id": note.id,
            "title": note.title,
            "version_id": latest.id if latest else None,
            **_section_view(section),
            "content": blocks[section["start"] : section["end"]],
        }

    def _replace_note_section(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}
        permission_error = self._edit_permission_error(note)
        if permission_error:
            return permission_error
        replacement = input.get("content")
        if not isinstance(replacement, list) or not all(
            isinstance(block, dict) for block in replacement
        ):
            return {"error": "content must be an array of Tiptap block objects"}

        expected = input.get("expected_version_id")
        section_id = str(input.get("section_id") or "")
        try:
            with transaction.atomic():
                locked = Note.objects.select_for_update().get(id=note.id)
                stale = self._stale_version_error(locked, expected)
                if stale:
                    return stale
                latest = locked.latest_version
                document = _structured_document(latest)
                if document is None:
                    return {"error": "structured note content is no longer available"}
                section = _find_section(document, section_id)
                if section is None:
                    return {
                        "error": (
                            f"section {section_id!r} not found; call "
                            "get_note_outline again"
                        )
                    }
                blocks = _document_blocks(document)
                document["content"] = (
                    blocks[: section["start"]] + replacement + blocks[section["end"] :]
                )
                version = self._create_version(locked, document)
        except (ValueError, Note.DoesNotExist) as exc:
            return {"error": str(exc)}
        return {
            "note_id": note.id,
            "section_id": section_id,
            "version_id": version.id,
            "saved": True,
        }

    def _read_note(self, input: dict) -> dict:
        note = self._get_readable_note(input.get("note_id"))
        if note is None:
            return {"error": f"note {input.get('note_id')} not found or not accessible"}
        latest = note.latest_version
        if _structured_document(latest) is not None:
            return {
                "error": (
                    "read_note is restricted to legacy note content; "
                    "start a new turn to use section tools"
                )
            }
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

        permission_error = self._edit_permission_error(note)
        if permission_error:
            return permission_error

        expected = input.get("expected_version_id")
        try:
            with transaction.atomic():
                # Lock the note row so the version check and the append are
                # one atomic step; a concurrent edit blocks here and then
                # sees the new latest_version_id (-> stale error) on entry.
                locked = Note.objects.select_for_update().get(id=note.id)
                stale = self._stale_version_error(locked, expected)
                if stale:
                    return stale
                if _structured_document(locked.latest_version) is not None:
                    return {
                        "error": (
                            "edit_note is restricted to legacy note content; "
                            "start a new turn to use section tools"
                        )
                    }
                version = self._create_version(locked, input.get("content"))
        except (ValueError, Note.DoesNotExist) as exc:
            return {"error": str(exc)}
        return {"note_id": note.id, "version_id": version.id, "saved": True}

    def _edit_permission_error(self, note: Note) -> dict | None:
        permissions = note.permissions
        if permissions.has_admin_user(self._user) or permissions.has_editor_user(
            self._user
        ):
            return None
        return {"error": f"no edit permission on note {note.id}"}

    def _stale_version_error(self, note: Note, expected) -> dict | None:
        if note.latest_version_id == expected:
            return None
        refresh_tool = (
            "get_note_outline"
            if self._mode == SECTION_NOTE_MODE
            else "read_note"
        )
        return {
            "error": (
                f"stale version: note {note.id} is at version "
                f"{note.latest_version_id}, expected {expected}; call "
                f"{refresh_tool} again and re-apply your edit"
            )
        }

    def _create_version(self, note: Note, content: dict) -> NoteContent:
        return self._service.create_version(
            note,
            content,
            created_by=self._user,
            created_via=NoteContent.CREATED_VIA_AGENT,
            parent_version_id=note.latest_version_id,
        )

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
