"""Rules for the grant (RFP) a preregistration draft applies to.

The note API and the notebook agent both select a grant, so the rules that
decide whether a selection is allowed live here rather than in either entry
point, where they would drift apart.
"""

from note.models import Note
from purchase.models import Grant
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import PREREGISTRATION

NOT_PREREGISTRATION = "Only preregistration notes can select a grant."
GRANT_INACTIVE = "Grant is no longer accepting applications."
NOTE_PUBLISHED = "Published notes cannot change grants."


class GrantSelectionError(Exception):
    """A grant selection the note's or the grant's state does not allow."""


def selectable_grants(user):
    """Grants ``user`` may select: live grants on a post they can see."""
    visible_document_ids = ResearchhubPost.objects.visible_to(user).values(
        "unified_document_id"
    )
    return Grant.objects.filter(
        unified_document_id__in=visible_document_ids,
        unified_document__is_removed=False,
    )


def validate_selection(*, document_type, grant) -> None:
    """Raise when ``grant`` cannot be selected by a note of ``document_type``.

    Clearing a selection (``grant`` of ``None``) is always allowed, so a note
    can leave the preregistration type without stranding a grant on it.
    """
    if grant is None:
        return
    if document_type != PREREGISTRATION:
        raise GrantSelectionError(NOT_PREREGISTRATION)
    if not grant.is_active():
        raise GrantSelectionError(GRANT_INACTIVE)


def select_grant(*, note: Note, grant: Grant | None) -> Note:
    """Persist ``grant`` as ``note``'s selected RFP.

    The whole operation for non-HTTP callers: the API's serializer applies
    ``validate_selection`` itself and the view owns its own 409 for a published
    note, so this mirrors both rather than being called from there.
    """
    if hasattr(note, "post"):
        raise GrantSelectionError(NOTE_PUBLISHED)
    validate_selection(document_type=note.document_type, grant=grant)
    note.selected_grant = grant
    note.save(update_fields=["selected_grant", "updated_date"])
    return note
