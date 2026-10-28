"""Mark an image attached in a note's chat as the logo for its generated covers.

The cover generator places the recorded logo in every banner it makes for the
note. There is no other way to give it one: the user attaches the logo in the
chat like any other file and says what it is.
"""

import logging

from note.models import Note
from research_ai.models import AgentFile, NoteCoverLogo
from research_ai.models.agent_file import IN_CHAT
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent_files.extraction import is_image_type

logger = logging.getLogger(__name__)


class CoverLogoToolset:
    SET_COVER_LOGO = "set_cover_logo"

    NOTE_NOT_ACCESSIBLE = "note not found or not accessible"

    def __init__(self, *, note: Note, conversation, user):
        self._note_id = note.id
        self._conversation = conversation
        self._user = user

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=self.SET_COVER_LOGO,
                description=(
                    "Use an image attached in this chat as the organization's "
                    "logo in this note's AI-generated cover images, replacing "
                    "any logo set before, or pass null to stop using one. Only "
                    "use it when the user says an attachment is their logo or "
                    "asks for it on the cover -- never for a figure or a "
                    "screenshot. Covers generated afterwards place the logo "
                    "exactly as uploaded."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "attachment_id": {
                            "type": ["integer", "null"],
                            "description": (
                                "Id of an attached image, from the attachment "
                                "list, or null to remove the cover logo."
                            ),
                        }
                    },
                    "required": ["attachment_id"],
                },
                handler=self._set_cover_logo,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _set_cover_logo(self, args: dict) -> dict:
        try:
            note, error = self._editable_note()
            if error is not None:
                return error
            if "attachment_id" not in args:
                return {
                    "error": "attachment_id is required; pass null to remove the logo"
                }

            attachment_id = args["attachment_id"]
            if attachment_id is None:
                NoteCoverLogo.objects.filter(note=note).delete()
                return {"note_id": note.id, "cover_logo": None, "saved": True}

            file, error = self._attached_image(attachment_id)
            if error is not None:
                return error
            NoteCoverLogo.objects.update_or_create(
                note=note, defaults={"file": file, "set_by": self._user}
            )
            return {
                "note_id": note.id,
                "cover_logo": {"attachment_id": file.id, "filename": file.filename},
                "saved": True,
            }
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("cover logo write failed for note %s", self._note_id)
            return {"error": "setting the cover logo is temporarily unavailable"}

    def _editable_note(self) -> tuple[Note | None, dict | None]:
        if self._user is None or not getattr(self._user, "is_authenticated", False):
            return None, {"error": self.NOTE_NOT_ACCESSIBLE}
        note = (
            Note.objects.select_related("unified_document")
            .filter(id=self._note_id, unified_document__is_removed=False)
            .first()
        )
        if note is None or not note.permissions.has_user(self._user):
            return None, {"error": self.NOTE_NOT_ACCESSIBLE}
        permissions = note.permissions
        if not (
            permissions.has_admin_user(self._user)
            or permissions.has_editor_user(self._user)
        ):
            return None, {"error": "no permission to change this note's cover logo"}
        return note, None

    def _attached_image(self, attachment_id) -> tuple[AgentFile | None, dict | None]:
        if isinstance(attachment_id, bool) or not isinstance(attachment_id, int):
            return None, {"error": "attachment_id must be an integer or null"}
        file = (
            AgentFile.objects.defer("text")
            .filter(
                IN_CHAT,
                id=attachment_id,
                conversation=self._conversation,
                source=AgentFile.Source.UPLOAD,
                status=AgentFile.Status.READY,
            )
            .first()
        )
        if file is None:
            return None, {"error": "no uploaded attachment with that id in this chat"}
        if not is_image_type(file.content_type):
            return None, {"error": "the cover logo must be an image attachment"}
        return file, None
