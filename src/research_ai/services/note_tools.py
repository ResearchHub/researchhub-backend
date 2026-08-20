"""Notebook note tools for the agent core.

``NoteToolset`` lets an agent read and edit Tiptap notes on behalf of a
specific user. Reads hand the model the note's top-level blocks in the
compact dialect of ``utils.prosemirror``, indexed by position, plus a version
id. Edits are block-level operations (insert/replace/delete) against those
indices, guarded by that version id (optimistic concurrency), with the new
blocks validated against the vendored editor schema before anything is
stored. Tool traffic thus stays proportional to the change, not to the note:
the model never receives or regenerates the parts of the document it is not
touching. Each edit appends a new ``NoteContent`` version rather than
mutating in place, so any agent edit is recoverable from history.

Stored note content parses against the vendored schema (pre-schema content
has been cleaned up), so a note that somehow does not is reported to the
model as an error rather than served in a degraded form. A note with no
version yet reads as ``blocks: null`` and is populated by a first insert.

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
from note.services.note_content_service import NoteContentService
from research_ai.services.agent import Tool, Toolset
from research_ai.services.note_block_edits import (
    apply_block_edits,
    check_block_edits,
    parse_block_edits,
)
from researchhub_document.registered_report_note_metadata import parse_note_json
from utils.prosemirror import BLOCK_EDITOR, compact_blocks, parse_blocks

logger = logging.getLogger(__name__)

READ_NOTE = "read_note"
EDIT_NOTE = "edit_note"

_BLOCK_FORMAT = (
    "Blocks use a compact Tiptap form: a bare string at block level is a "
    "plain paragraph; inside a block's `content`, a bare string is unmarked "
    "text; attributes equal to the editor default are omitted."
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
                    "Read a ResearchHub notebook note. Returns the note "
                    "title, the version_id that edit_note requires, "
                    "block_count, and the note body as `blocks`: a map from "
                    'top-level block index ("0", "1", ...) to that block. '
                    f"{_BLOCK_FORMAT} A note with no content yet reads as "
                    "`blocks` null; populate it with an insert."
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
                    "Edit a note with block operations: insert new blocks at "
                    "a position, replace an inclusive range of blocks, or "
                    "delete one. Indices refer to the `blocks` map from "
                    "read_note; all edits in one call apply together against "
                    "that same numbering, so they never shift each other. "
                    "Pass the version_id from your latest read_note or "
                    "edit_note result as expected_version_id; the edit is "
                    "rejected as stale if the note changed since. "
                    "Send only the blocks you are changing -- "
                    "untouched blocks stay exactly as stored. "
                    f"{_BLOCK_FORMAT} New blocks are validated against the "
                    "editor schema; invalid ones reject the whole edit. Each "
                    "edit is saved as a new version, so prior content is "
                    "kept as history."
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
                        "edits": {
                            "type": "array",
                            "minItems": 1,
                            "description": (
                                "Operations on the block indices you read, "
                                "applied as one batch."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "op": {
                                        "type": "string",
                                        "enum": ["insert", "replace", "delete"],
                                    },
                                    "at": {
                                        "type": "integer",
                                        "description": (
                                            "insert: position to insert before "
                                            "(0 = start, block_count = end)."
                                        ),
                                    },
                                    "from": {
                                        "type": "integer",
                                        "description": (
                                            "replace/delete: first block index."
                                        ),
                                    },
                                    "to": {
                                        "type": "integer",
                                        "description": (
                                            "replace/delete: last block index, "
                                            "inclusive."
                                        ),
                                    },
                                    "blocks": {
                                        "type": "array",
                                        "items": {"type": ["object", "string"]},
                                        "description": (
                                            "insert/replace: new blocks in the "
                                            "compact form read_note returns."
                                        ),
                                    },
                                },
                                "required": ["op"],
                            },
                        },
                    },
                    "required": ["note_id", "expected_version_id", "edits"],
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
        # normalize before block extraction.
        doc = parse_note_json(latest.json) if latest else None
        if doc is None:
            blocks = None
        else:
            try:
                blocks = compact_blocks(BLOCK_EDITOR, doc)
            except ValueError as exc:
                # Stored content is expected to parse (pre-schema notes were
                # cleaned up), so surface the mismatch instead of hiding it.
                logger.warning("note %s content fails the editor schema", note.id)
                return {"error": f"note {note.id} content could not be read: {exc}"}
        result = {
            "note_id": note.id,
            "title": note.title,
            "version_id": latest.id if latest else None,
            "block_count": 0 if blocks is None else len(blocks),
            "blocks": (
                None
                if blocks is None
                else {str(index): block for index, block in enumerate(blocks)}
            ),
        }
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

        # Parse the operations and schema-validate their payload blocks
        # before taking any lock; neither depends on the stored document.
        try:
            edits = parse_block_edits(input.get("edits"))
            for index, edit in enumerate(edits):
                if edit.blocks is not None:
                    try:
                        edit.blocks = parse_blocks(BLOCK_EDITOR, edit.blocks)
                    except ValueError as exc:
                        raise ValueError(f"edits[{index}]: {exc}") from exc
        except ValueError as exc:
            return {"error": str(exc)}

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
                stored = (
                    parse_note_json(locked.latest_version.json)
                    if locked.latest_version
                    else None
                )
                base = stored.get("content") if stored else None
                base = base if isinstance(base, list) else []
                check_block_edits(edits, len(base))
                content = apply_block_edits(base, edits)
                if not content:
                    return {
                        "error": (
                            "these edits would leave the note empty; "
                            "a note needs at least one block"
                        )
                    }
                # Carry the stored root over (its system-owned attrs with it),
                # rewriting only `content` -- and the root type: reads ignore
                # it, so a malformed one must not make the note uneditable.
                document = dict(stored) if stored else {}
                document["type"] = "doc"
                document["content"] = content
                version = self._service.create_version(
                    locked,
                    document,
                    created_by=self._user,
                    created_via=NoteContent.CREATED_VIA_AGENT,
                    # The verified expected version is the base this edit was
                    # applied against.
                    parent_version_id=locked.latest_version_id,
                )
        except (ValueError, Note.DoesNotExist) as exc:
            return {"error": str(exc)}
        return {
            "note_id": note.id,
            "version_id": version.id,
            "saved": True,
            "block_count": len(content),
        }

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
