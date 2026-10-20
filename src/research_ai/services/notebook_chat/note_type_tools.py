"""A tool that switches the chat's note between an RFP and a proposal.

The switch goes through the note API's serializer, so the same rules decide it.
"""

import logging

from django.db import transaction

from note.models import Note
from note.serializers.note_serializer import NoteSerializer
from note.services.note_draft_service import DraftDetailsError, update_grant_settings
from research_ai.services.agent import Tool, Toolset
from research_ai.services.note_tools import notify_note_updated
from research_ai.services.notebook_chat.rfp_details_tools import (
    RFP_DETAIL_PROPERTIES,
    RFPDetailsToolset,
    rfp_details_values,
)
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)

logger = logging.getLogger(__name__)

CHANGE_NOTE_TYPE = "change_note_type"
_TYPE_NAMES = {GRANT: "an RFP", PREREGISTRATION: "a proposal"}
_NEXT_STEPS = {
    GRANT: (
        "The note is now an RFP. Publishing needs an amount and a description, "
        "and an RFP normally names a contact: tell the user which are still "
        "empty and ask for the values only they can give. Never invent an "
        "amount, an organization, a contact, or the application visibility. "
        "read_rfp_details and update_rfp_details are available from the "
        "user's next message. The body may still read as the user's own "
        "study: offer to rewrite it as a call for applicants."
    ),
    PREREGISTRATION: (
        "The note is now a proposal. From the user's next message you can "
        "read and set the RFP it applies to: offer to find matching RFPs with "
        "search_grants, and let the user pick one. The funding goal and the "
        "proposal's other Details are the user's to fill in when they publish. "
        "The body may still read as a call for applicants: offer to rewrite it "
        "as the user's study plan."
    ),
}


class _SwitchRefusedError(Exception):
    """A switch the note's state or the arguments do not allow."""


class NoteTypeToolset:
    """Switch ``note`` between an RFP (GRANT) and a proposal (PREREGISTRATION).

    ``asking`` is set for a turn that tells the agent to offer the switch: the
    user has not answered yet, so the tool refuses.
    """

    def __init__(self, *, note: Note, user, asking: bool = False):
        self._note = note
        self._user = user
        self._asking = asking

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=CHANGE_NOTE_TYPE,
                description=(
                    "Switch this note between an RFP (GRANT: a funding call "
                    "that invites other researchers to apply) and a proposal "
                    "(PREREGISTRATION: the user's plan for a study they will "
                    "run themselves). Call it only when the user asked for "
                    "this switch or said yes to it in their latest message, "
                    "never on your own judgment. The body stays as it is, and "
                    "leaving a proposal clears the RFP it applies to. When "
                    "switching to an RFP, pass rfp_details to fill in its "
                    "Details: a short description drawn from the note, and an "
                    "amount, organization, contacts, or visibility only when "
                    "the user gave them. A published note cannot change type."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "document_type": {
                            "type": "string",
                            "enum": [GRANT, PREREGISTRATION],
                            "description": (
                                "GRANT for an RFP, PREREGISTRATION for a proposal."
                            ),
                        },
                        "rfp_details": {
                            "type": "object",
                            "properties": RFP_DETAIL_PROPERTIES,
                            "description": (
                                "Only when switching to GRANT: the RFP's "
                                "Details to fill in."
                            ),
                        },
                    },
                    "required": ["document_type"],
                },
                handler=self._change_note_type,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _change_note_type(self, args: dict) -> dict:
        args = args or {}
        try:
            if self._asking:
                return {
                    "error": (
                        "the user has not answered yet: ask whether they want "
                        "the switch, and make it after they say yes"
                    )
                }
            target = str(args.get("document_type") or "").strip().upper()
            if target not in _TYPE_NAMES:
                return {"error": "document_type must be GRANT or PREREGISTRATION"}
            values, error = self._details_values(target, args.get("rfp_details"))
            if error is not None:
                return error
            try:
                note, previous, cleared = self._switch(target, values)
            except _SwitchRefusedError as exc:
                return {"error": str(exc)}
            notify_note_updated(note)
            return self._result(note, previous, cleared)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("note type change failed for note %s", self._note.id)
            return {"error": "changing the note type is temporarily unavailable"}

    @staticmethod
    def _details_values(target: str, raw) -> tuple[dict | None, dict | None]:
        """The RFP Details to save with the switch; none when nothing is passed."""
        if raw is None:
            return None, None
        if not isinstance(raw, dict):
            return None, {"error": "rfp_details must be an object"}
        # Models pad optional arguments with nulls.
        supplied = {key: value for key, value in raw.items() if value is not None}
        if not supplied:
            return None, None
        if target != GRANT:
            return None, {"error": "rfp_details applies only when switching to GRANT"}
        return rfp_details_values(supplied)

    def _switch(self, target: str, values: dict | None):
        """Change the type, and save ``values`` to the new RFP's Details.

        Returns the note, its previous type, and the grant the switch cleared.
        """
        try:
            with transaction.atomic():
                note = (
                    Note.objects.select_for_update()
                    .filter(id=self._note.id, unified_document__is_removed=False)
                    .first()
                )
                if note is None:
                    raise _SwitchRefusedError(f"note {self._note.id} is not accessible")
                permissions = note.permissions
                if not (
                    permissions.has_admin_user(self._user)
                    or permissions.has_editor_user(self._user)
                ):
                    raise _SwitchRefusedError(f"no edit permission on note {note.id}")
                if hasattr(note, "post"):
                    raise _SwitchRefusedError("a published note cannot change type")
                previous = note.document_type
                if previous == target:
                    raise _SwitchRefusedError(
                        f"the note is already {_TYPE_NAMES[target]}"
                    )
                if previous not in _TYPE_NAMES:
                    raise _SwitchRefusedError(
                        "only an RFP or a proposal note can switch to the other"
                    )
                data = {"document_type": target}
                cleared = note.selected_grant
                if cleared is not None:
                    # The note API refuses a grant on a note that is not a
                    # proposal; a client clears it the same way.
                    data["selected_grant"] = None
                serializer = NoteSerializer(note, data=data, partial=True)
                if not serializer.is_valid():
                    raise _SwitchRefusedError(
                        f"the switch was refused: {serializer.errors}"
                    )
                note = serializer.save()
                if values:
                    update_grant_settings(note=note, values=values)
        except DraftDetailsError as exc:
            raise _SwitchRefusedError(str(exc)) from exc
        return note, previous, cleared

    def _result(self, note: Note, previous: str, cleared) -> dict:
        target = note.document_type
        result = {
            "note_id": note.id,
            "document_type": target,
            "previous_document_type": previous,
            "next_steps": _NEXT_STEPS[target],
        }
        if cleared is not None:
            post = cleared.unified_document.posts.first()
            result["cleared_selected_rfp"] = {
                "grant_id": cleared.id,
                "title": post.title if post else None,
            }
        if target == GRANT:
            result["rfp_details"] = RFPDetailsToolset(
                user=self._user, get_note=lambda _note_id: note
            ).details(note)
        return result
