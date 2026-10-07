"""Tools that read and fill a GRANT note's Details form (``GrantSettings``).

Nothing here publishes: the live ``Grant`` is created when the user publishes.
"""

import logging
from collections.abc import Callable

from note.models import GrantSettings, Note
from note.serializers.note_serializer import GrantSettingsSerializer
from note.services.note_draft_service import DraftDetailsError, update_grant_settings
from purchase.models import Grant
from purchase.related_models.constants.currency import USD
from research_ai.services.agent import Tool, Toolset
from research_ai.services.note_tools import notify_note_updated
from researchhub_document.related_models.constants.document_type import GRANT

logger = logging.getLogger(__name__)

READ_RFP_DETAILS = "read_rfp_details"
UPDATE_RFP_DETAILS = "update_rfp_details"
_MAX_DESCRIPTION_CHARS = 4000
_VISIBILITY_CHOICES = tuple(value for value, _ in Grant.APPLICATION_VISIBILITY_CHOICES)
# Tool argument -> the field the note API's serializer validates it as.
_DETAIL_FIELDS = {
    "amount": "amount",
    "organization": "organization",
    "description": "description",
    "contact_user_ids": "contact_ids",
    "application_visibility": "application_visibility",
}
_DETAIL_ARGS = {field: arg for arg, field in _DETAIL_FIELDS.items()}
_NOTE_ID_SCHEMA = {
    "type": "integer",
    "description": "Id of the RFP (GRANT) note.",
}


class RFPDetailsToolset:
    """Read and fill the Details form of the RFP notes ``get_note`` resolves.

    Pass the note tools' resolver so a note created this turn is in scope.
    """

    def __init__(self, *, user, get_note: Callable[[object], Note | None]):
        self._user = user
        self._get_note = get_note

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=READ_RFP_DETAILS,
                description=(
                    "Read the Details form of an RFP (GRANT) note: funding "
                    "amount in USD, organization, short description, contacts, "
                    "and whether applications are private or public. These "
                    "are the values the RFP is published with, separate from "
                    "the note body. Use it to tell the user what is filled in "
                    "or still missing, and before replacing a value they may "
                    "have entered themselves. Once the RFP is published it "
                    "returns the live terms, with `published` true."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"note_id": _NOTE_ID_SCHEMA},
                    "required": ["note_id"],
                },
                handler=self._read_rfp_details,
            ),
            Tool(
                name=UPDATE_RFP_DETAILS,
                description=(
                    "Fill in the Details form of an RFP (GRANT) note. Only the "
                    "fields you pass change; omit a field to leave it as it "
                    "is. Set values the user gave or confirmed -- never invent "
                    "an amount, an organization, or a contact. This saves the "
                    "draft form only: the user still reviews it and publishes, "
                    "and a published RFP's Details cannot be changed here."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "note_id": _NOTE_ID_SCHEMA,
                        "amount": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "description": (
                                "Total funding offered, in US dollars (the "
                                "currency is always USD), as a plain number "
                                "such as 50000."
                            ),
                        },
                        "organization": {
                            "type": "string",
                            "description": (
                                "Name of the funding organization. An empty "
                                "string clears it."
                            ),
                        },
                        "description": {
                            "type": "string",
                            "maxLength": _MAX_DESCRIPTION_CHARS,
                            "description": (
                                "Short summary of what the RFP funds, a few "
                                "sentences; the full call belongs in the note "
                                "body. An empty string clears it."
                            ),
                        },
                        "contact_user_ids": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": (
                                "ResearchHub user ids of the people who manage "
                                "this RFP; replaces the current contacts, and "
                                "an empty list clears them. For the user "
                                "themself use current_user.user_id from "
                                "read_rfp_details. These are user ids, not "
                                "author-profile ids -- never guess one."
                            ),
                        },
                        "application_visibility": {
                            "type": "string",
                            "enum": list(_VISIBILITY_CHOICES),
                            "description": (
                                "PRIVATE: applicants' proposals must be "
                                "private. PUBLIC: they must be public. "
                                "OPTIONAL: each applicant chooses."
                            ),
                        },
                    },
                    "required": ["note_id"],
                },
                handler=self._update_rfp_details,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def _read_rfp_details(self, args: dict) -> dict:
        note_id = (args or {}).get("note_id")
        try:
            note, error = self._rfp_note(note_id)
            if error is not None:
                return error
            return self._details(note)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("RFP details read failed for note %s", note_id)
            return {"error": "RFP details are temporarily unavailable"}

    def _update_rfp_details(self, args: dict) -> dict:
        args = args or {}
        note_id = args.get("note_id")
        try:
            # Access before arguments: an unreachable note is answered the same
            # way whatever the model asked for.
            note, error = self._editable_rfp_note(note_id)
            if error is not None:
                return error
            payload, error = _details_payload(args)
            if error is not None:
                return error
            serializer = GrantSettingsSerializer(data=payload, partial=True)
            if not serializer.is_valid():
                return {"error": _validation_message(serializer.errors)}
            values = serializer.validated_data
            # The draft form stores any amount; publishing needs a positive one.
            if "amount" in values and values["amount"] <= 0:
                return {"error": "amount must be greater than 0"}

            try:
                update_grant_settings(note=note, values=values)
            except DraftDetailsError as exc:
                return {"error": str(exc)}
            notify_note_updated(note)
            return {**self._details(note), "saved": True}
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("RFP details write failed for note %s", note_id)
            return {"error": "updating RFP details is temporarily unavailable"}

    # -- helpers ----------------------------------------------------------

    def _rfp_note(self, note_id) -> tuple[Note | None, dict | None]:
        """The readable note ``note_id`` when it is an RFP draft."""
        note = self._get_note(note_id)
        if note is None:
            return None, {"error": f"note {note_id} not found or not accessible"}
        if note.document_type != GRANT:
            return None, {
                "error": (
                    f"note {note.id} is not an RFP (GRANT) note; only an RFP "
                    "has a Details form"
                )
            }
        return note, None

    def _editable_rfp_note(self, note_id) -> tuple[Note | None, dict | None]:
        """The RFP draft ``note_id`` when the user may change it."""
        note, error = self._rfp_note(note_id)
        if error is not None:
            return None, error
        permissions = note.permissions
        if not (
            permissions.has_admin_user(self._user)
            or permissions.has_editor_user(self._user)
        ):
            return None, {"error": f"no edit permission on note {note.id}"}
        return note, None

    def _details(self, note: Note) -> dict:
        """The RFP's terms, plus the id that names the user as a contact."""
        post = getattr(note, "post", None)
        if post is not None:
            # Publishing does not sync the draft form, so it is stale from here on.
            settings = post.unified_document.grants.first()
        else:
            settings = getattr(note, "grant_settings", None)
        # An unsaved row stands in for terms nobody has filled in.
        settings = settings or GrantSettings()
        contacts = settings.contacts.all() if settings.pk else []
        details = {
            "note_id": note.id,
            "published": post is not None,
            "amount": None if settings.amount is None else str(settings.amount),
            "currency": settings.currency or USD,
            "organization": settings.organization or "",
            "description": settings.description[:_MAX_DESCRIPTION_CHARS],
            "application_visibility": settings.application_visibility or None,
            "contacts": [_user_ref(contact) for contact in contacts],
            "current_user": _user_ref(self._user),
        }
        if len(settings.description) > _MAX_DESCRIPTION_CHARS:
            details["description_is_truncated"] = True
        return details


def _user_ref(user) -> dict:
    name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    return {"user_id": user.id, "name": name}


def _details_payload(args: dict) -> tuple[dict | None, dict | None]:
    """The note API payload for the Details fields ``args`` supplies.

    Null means "not supplied": models pad optional arguments with nulls.
    """
    payload = {
        field: args[arg]
        for arg, field in _DETAIL_FIELDS.items()
        if args.get(arg) is not None
    }
    if not payload:
        return None, {
            "error": (
                "pass at least one Details field to update: "
                + ", ".join(_DETAIL_FIELDS)
            )
        }

    if "amount" in payload:
        payload["currency"] = USD

    description = payload.get("description")
    if isinstance(description, str) and len(description) > _MAX_DESCRIPTION_CHARS:
        return None, {
            "error": (
                f"description must be at most {_MAX_DESCRIPTION_CHARS} "
                "characters; put the full call in the note body"
            )
        }

    if "application_visibility" in payload:
        visibility = payload["application_visibility"]
        if isinstance(visibility, str):
            visibility = visibility.strip().upper()
        # The field itself accepts a blank, which would unset the choice.
        if visibility not in _VISIBILITY_CHOICES:
            return None, {
                "error": (
                    "application_visibility must be one of "
                    + ", ".join(_VISIBILITY_CHOICES)
                )
            }
        payload["application_visibility"] = visibility

    if "contact_ids" in payload:
        contact_ids, error = _parse_user_ids(payload["contact_ids"])
        if error is not None:
            return None, error
        payload["contact_ids"] = contact_ids
    return payload, None


def _parse_user_ids(raw_ids) -> tuple[list[int] | None, dict | None]:
    """Whole-number user ids in the order given, without repeats.

    A pk lookup would coerce 1.9 to 1, so only integers and digit strings pass.
    """
    error = {"error": "contact_user_ids must be a list of ResearchHub user ids"}
    if not isinstance(raw_ids, list):
        return None, error
    user_ids = []
    for raw_id in raw_ids:
        if isinstance(raw_id, int) and not isinstance(raw_id, bool):
            user_ids.append(raw_id)
        elif (
            isinstance(raw_id, str)
            and raw_id.strip().isascii()
            and raw_id.strip().isdigit()
        ):
            user_ids.append(int(raw_id.strip()))
        else:
            return None, error
    return list(dict.fromkeys(user_ids)), None


def _validation_message(errors: dict) -> str:
    """Serializer errors as one line, named by tool argument."""
    return "; ".join(
        f"{_DETAIL_ARGS.get(field, field)}: "
        + " ".join(str(message) for message in messages)
        for field, messages in errors.items()
    )
