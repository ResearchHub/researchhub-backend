"""Draft Details writes for a notebook note.

Nothing here creates a live ``Grant``, ``Fundraise``, escrow, application, or
nonprofit link; those remain publish-time concerns.
"""

from django.db import transaction

from note.models import GrantSettings, Note, PreregistrationSettings
from researchhub_document.related_models.constants.document_type import GRANT
from user.models import Author

NOT_RFP_NOTE = "Only RFP notes have RFP details."
NOTE_PUBLISHED = "Published notes cannot change RFP details."


class DraftDetailsError(Exception):
    """A draft Details write the note's state does not allow."""


def save_note_draft_details(
    note: Note,
    *,
    authors: list[Author] | None,
    grant_settings: dict | None,
    preregistration_settings: dict | None,
) -> None:
    """Write every supplied relationship, leaving omitted ones untouched."""
    if authors is not None:
        note.reset_note_authors([author.id for author in authors])
    if grant_settings is not None:
        _save_grant_settings(note, grant_settings)
    if preregistration_settings is not None:
        _save_preregistration_settings(note, preregistration_settings)


def update_grant_settings(*, note: Note, values: dict) -> GrantSettings:
    """Write the supplied grant Details fields for a non-HTTP caller.

    Mirrors the note API, which refuses non-grant and published notes itself.
    """
    with transaction.atomic():
        # Publishing inserts a post that references this row, so it waits here.
        locked = Note.objects.select_for_update().get(id=note.id)
        if hasattr(locked, "post"):
            raise DraftDetailsError(NOTE_PUBLISHED)
        if locked.document_type != GRANT:
            raise DraftDetailsError(NOT_RFP_NOTE)
        _save_grant_settings(note, dict(values))
        note.save(update_fields=["updated_date"])
    return note.grant_settings


def _save_grant_settings(note: Note, values: dict) -> None:
    """Save the note's draft grant form and replace its contacts.

    The saved row replaces the one ``note`` was loaded with, so a response
    rendered from the same instance shows what this request just wrote.
    """
    contacts = values.pop("contacts", None)
    grant_settings, _ = GrantSettings.objects.update_or_create(
        note=note, defaults=values
    )
    if contacts is not None:
        grant_settings.contacts.set(contacts)
    note.grant_settings = grant_settings


def _save_preregistration_settings(note: Note, values: dict) -> None:
    """Save the note's draft preregistration form.

    The saved row replaces the one ``note`` was loaded with, so a response
    rendered from the same instance shows what this request just wrote.
    """
    preregistration_settings, _ = PreregistrationSettings.objects.update_or_create(
        note=note, defaults=values
    )
    note.preregistration_settings = preregistration_settings
