"""A proposal's or RFP's generated cover, from its chat.

``set_cover_logo`` marks an image attached in the chat as the logo the cover
generator places in every banner it makes for the note; there is no other way
to give it one. ``generate_cover_image`` generates a banner from the draft's
saved details and makes it the draft's cover.
"""

import logging

from note.models import Note
from research_ai.models import AgentFile, CoverImageGeneration, NoteCoverLogo
from research_ai.models.agent_file import IN_CHAT
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent_files.extraction import is_image_type
from research_ai.services.cover_image_service import CoverImageService
from research_ai.services.usage_budget import UsageLimitExceededError

logger = logging.getLogger(__name__)


class CoverImageToolset:
    SET_COVER_LOGO = "set_cover_logo"
    GENERATE_COVER_IMAGE = "generate_cover_image"

    NOTE_NOT_ACCESSIBLE = "note not found or not accessible"

    def __init__(
        self,
        *,
        note: Note,
        conversation,
        user,
        cover_images: CoverImageService | None = None,
    ):
        self._note_id = note.id
        self._conversation = conversation
        self._user = user
        self._cover_images = cover_images

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
            Tool(
                name=self.GENERATE_COVER_IMAGE,
                description=(
                    "Generate a cover banner for this proposal or RFP and make it "
                    "the draft's cover, replacing any cover it has. Each one costs "
                    "money from the user's daily AI budget: only use it when the "
                    "user asks for a cover, never on your own initiative. The "
                    "banner shows the saved title and details (for an RFP, its "
                    "organization, description and amount) and the cover logo, "
                    "if one is set, so save any changes to those first. Takes "
                    "up to a minute."
                ),
                input_schema={"type": "object", "properties": {}},
                handler=self._generate_cover_image,
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

    @property
    def cover_images(self) -> CoverImageService:
        # Built on first use: most turns never generate a cover.
        if self._cover_images is None:
            self._cover_images = CoverImageService()
        return self._cover_images

    def _generate_cover_image(self, args: dict) -> dict:
        try:
            note, error = self._editable_note()
            if error is not None:
                return error
            if hasattr(note, "post"):
                return {"error": "a published note's cover can't be changed here"}
            if not note.title.strip():
                return {"error": "give the note a title before generating a cover"}

            try:
                generation = self.cover_images.generate_for_note(self._user, note)
            except UsageLimitExceededError:
                return {"error": "the user's daily AI usage limit is reached"}
            if generation.status != CoverImageGeneration.Status.COMPLETED:
                return {"error": "could not generate a cover image; try again later"}
            return {
                "note_id": note.id,
                "cover_image_url": self.cover_images.image_url(generation.image_key),
                "saved": True,
            }
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("cover image generation failed for note %s", self._note_id)
            return {"error": "generating a cover is temporarily unavailable"}

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
            return None, {"error": "no permission to change this note's cover"}
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
