"""Grant discovery tools for the notebook chat agent."""

import logging

from note.models import Note
from note.services.grant_selection_service import (
    GrantSelectionError,
    select_grant,
    selectable_grants,
)
from purchase.services.grant_search_service import GrantSearchService
from research_ai.constants import BASE_FRONTEND_URL
from research_ai.services.agent import Tool, Toolset
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

logger = logging.getLogger(__name__)

SEARCH_GRANTS = "search_grants"
READ_SELECTED_RFP = "read_selected_rfp"
SET_SELECTED_RFP = "set_selected_rfp"
_MAX_QUERY_CHARS = 500
_MAX_DESCRIPTION_CHARS = 3000
_MAX_POST_CONTENT_CHARS = 3000
_EMPTY_INPUT_SCHEMA = {"type": "object", "properties": {}}
_SELECTED_RFP_NOT_ACCESSIBLE = "selected RFP not found or not accessible"
_NOTE_NOT_ACCESSIBLE = "this preregistration is not accessible"


def _grant_url(grant, post=None) -> str | None:
    if post is None:
        post = grant.unified_document.posts.first()
    if post is None or not post.id or not post.slug:
        return None
    return f"{BASE_FRONTEND_URL}/grant/{post.id}/{post.slug}"


class GrantSearchToolset:
    """Search application-ready grants as the conversation's user."""

    def __init__(
        self,
        *,
        user,
        service: GrantSearchService | None = None,
    ):
        self._user = user
        self._service = service or GrantSearchService()

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=SEARCH_GRANTS,
                description=(
                    "Search ResearchHub for active grants/RFPs relevant to a "
                    "preregistration. Use a focused topic, method, disease, or "
                    "research-area query derived from the note. Returns only "
                    "grants currently accepting applications that the user can "
                    "view, with their terms, deadlines, and ResearchHub URLs."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Focused keywords describing the proposed research."
                            ),
                            "maxLength": _MAX_QUERY_CHARS,
                        }
                    },
                    "required": ["query"],
                },
                handler=self._search_grants,
            )
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    def _search_grants(self, args: dict) -> dict:
        query = " ".join(str((args or {}).get("query") or "").split())
        if not query:
            return {"error": "query is required"}
        if len(query) > _MAX_QUERY_CHARS:
            return {"error": f"query exceeds {_MAX_QUERY_CHARS} characters"}

        try:
            grants = self._service.search(user=self._user, query=query)
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("grant search failed")
            return {"error": "grant search is temporarily unavailable"}

        return {
            "query": query,
            "grants": [self._serialize(grant) for grant in grants],
        }

    @staticmethod
    def _serialize(grant) -> dict:
        posts = list(grant.unified_document.posts.all())
        post = posts[0] if posts else None
        title = (grant.short_title or "").strip()
        if not title and post is not None:
            title = (post.title or "").strip()
        return {
            "id": grant.id,
            "title": title,
            "organization": (grant.organization or "").strip(),
            "description": (grant.description or "")[:_MAX_DESCRIPTION_CHARS],
            "post_content": (
                (post.renderable_text or "").strip()[:_MAX_POST_CONTENT_CHARS]
                if post is not None
                else ""
            ),
            "amount": str(grant.amount),
            "currency": grant.currency,
            "deadline": grant.end_date.isoformat() if grant.end_date else None,
            "application_visibility": grant.application_visibility,
            "url": _grant_url(grant, post),
        }


def _grant_terms(grant) -> dict:
    """The structured grant terms both selected-RFP tools report."""
    post = grant.unified_document.posts.first()
    title = (grant.short_title or "").strip()
    if not title and post is not None:
        title = (post.title or "").strip()
    return {
        "id": grant.id,
        "title": title,
        "organization": (grant.organization or "").strip(),
        "amount": str(grant.amount),
        "currency": grant.currency,
        "deadline": grant.end_date.isoformat() if grant.end_date else None,
        "application_visibility": grant.application_visibility,
        "url": _grant_url(grant, post),
    }


class SelectedRFPToolset:
    """Read and set the RFP one preregistration note applies to."""

    def __init__(self, *, note: Note, user):
        self._note_id = note.id
        self._user = user

    def build_tools(self) -> list[Tool]:
        return [
            Tool(
                name=READ_SELECTED_RFP,
                description=(
                    "Read the full RFP selected for this preregistration note. "
                    "Use it before evaluating fit, requirements, budget, "
                    "deadline, or revising the note for the selected funding "
                    "opportunity. Returns structured grant terms and the full "
                    "call text."
                ),
                input_schema=_EMPTY_INPUT_SCHEMA,
                handler=self._read_selected_rfp,
            ),
            Tool(
                name=SET_SELECTED_RFP,
                description=(
                    "Select the RFP this preregistration applies to, replacing "
                    "any current selection, or pass null to clear it. Only use "
                    "it when the user asks to apply to, switch to, or drop a "
                    "funding opportunity -- never to record one you merely "
                    "found. Take grant_id from search_grants; the grant must "
                    "still be accepting applications, and a published note "
                    "cannot change its RFP."
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "grant_id": {
                            "type": ["integer", "null"],
                            "description": (
                                "Id of the grant to select, from search_grants, "
                                "or null to clear the current selection."
                            ),
                        }
                    },
                    "required": ["grant_id"],
                },
                handler=self._set_selected_rfp,
            ),
        ]

    def as_toolset(self) -> Toolset:
        return Toolset(self.build_tools())

    # -- handlers ---------------------------------------------------------

    def _read_selected_rfp(self, _args: dict) -> dict:
        if self._user is None or not getattr(self._user, "is_authenticated", False):
            return {"error": _SELECTED_RFP_NOT_ACCESSIBLE}

        try:
            note = self._readable_note()
            if note is None:
                return {"error": _SELECTED_RFP_NOT_ACCESSIBLE}

            grant = note.selected_grant
            if grant is None:
                return {"error": "this preregistration has no selected RFP"}
            if grant.unified_document.is_removed or not (
                grant.unified_document.is_visible_to_user(self._user)
            ):
                return {"error": _SELECTED_RFP_NOT_ACCESSIBLE}

            return {**_grant_terms(grant), "rfp_text": grant.get_llm_context_text()}
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("selected RFP read failed for note %s", self._note_id)
            return {"error": "selected RFP is temporarily unavailable"}

    def _set_selected_rfp(self, args: dict) -> dict:
        if self._user is None or not getattr(self._user, "is_authenticated", False):
            return {"error": _NOTE_NOT_ACCESSIBLE}

        raw_id = (args or {}).get("grant_id")
        # Only an explicit null clears the selection; anything else must name a
        # grant, so a malformed id is never read as "unset the RFP".
        if raw_id is not None:
            try:
                grant_id = int(raw_id)
            except (TypeError, ValueError):
                return {"error": "grant_id must be a grant id or null"}
        else:
            grant_id = None

        try:
            note = self._readable_note()
            if note is None:
                return {"error": _NOTE_NOT_ACCESSIBLE}
            permissions = note.permissions
            if not (
                permissions.has_admin_user(self._user)
                or permissions.has_editor_user(self._user)
            ):
                return {"error": "no permission to change this note's selected RFP"}

            grant = None
            if grant_id is not None:
                # Same visibility rule the note API selects grants through: the
                # user must be able to see the grant's post.
                grant = (
                    selectable_grants(self._user)
                    .select_related("unified_document")
                    .prefetch_related("unified_document__posts")
                    .filter(id=grant_id)
                    .first()
                )
                if grant is None:
                    return {"error": f"grant {grant_id} not found or not accessible"}

            try:
                select_grant(note=note, grant=grant)
            except GrantSelectionError as exc:
                return {"error": str(exc)}
            self._notify_note_updated(note)

            if grant is None:
                return {"note_id": note.id, "selected_rfp": None, "saved": True}
            return {
                "note_id": note.id,
                "selected_rfp": _grant_terms(grant),
                "saved": True,
            }
        except Exception:  # noqa: BLE001 - tool failures are model-readable
            logger.exception("selected RFP write failed for note %s", self._note_id)
            return {"error": "selecting an RFP is temporarily unavailable"}

    @staticmethod
    def _notify_note_updated(note) -> None:
        """Nudge the notebook so an open client sees the new selection.

        The note API pushes this after every PATCH, and a selection writes no
        NoteContent, so without it nothing tells an open notebook the RFP
        changed. An ownerless note has no org room to push to, and a failing
        channel layer must not undo a write that already committed.
        """
        if note.organization_id is None:
            return
        try:
            note.notify_note_updated_title()
        except Exception:  # noqa: BLE001 - the selection is already saved
            logger.warning(
                "could not publish note update after an RFP selection", exc_info=True
            )

    def _readable_note(self) -> Note | None:
        """This toolset's note, or ``None`` when the user cannot reach it."""
        try:
            note = (
                Note.objects.select_related(
                    "unified_document", "selected_grant__unified_document"
                )
                .prefetch_related("selected_grant__unified_document__posts")
                .get(
                    id=self._note_id,
                    document_type=PREREGISTRATION,
                    unified_document__is_removed=False,
                )
            )
        except Note.DoesNotExist:
            return None
        return note if note.permissions.has_user(self._user) else None
