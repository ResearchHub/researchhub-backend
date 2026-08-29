"""Draft Details writes for a notebook note.

Nothing here creates a live ``Grant``, ``Fundraise``, escrow, application, or
nonprofit link; those remain publish-time concerns.
"""

from hub.models import Hub
from note.models import Note, NoteFundraise, NoteGrant
from user.models import Author


def save_note_draft_details(
    note: Note,
    *,
    authors: list[Author] | None,
    hubs: list[Hub] | None,
    grant_details: dict | None,
    fundraise_details: dict | None,
) -> None:
    """Write every supplied relationship, leaving omitted ones untouched."""
    if authors is not None:
        note.reset_note_authors([author.id for author in authors])
    if hubs is not None:
        note.unified_document.hubs.set(hubs)
    if grant_details is not None:
        _save_grant_details(note, grant_details)
    if fundraise_details is not None:
        _save_fundraise_details(note, fundraise_details)


def _save_grant_details(note: Note, values: dict) -> None:
    """Save the note's draft grant form and replace its contacts.

    The saved row replaces the one ``note`` was loaded with, so a response
    rendered from the same instance shows what this request just wrote.
    """
    contacts = values.pop("contacts", None)
    grant_details, _ = NoteGrant.objects.update_or_create(note=note, defaults=values)
    if contacts is not None:
        grant_details.contacts.set(contacts)
    note.grant_details = grant_details


def _save_fundraise_details(note: Note, values: dict) -> None:
    """Save the note's draft fundraise form.

    The saved row replaces the one ``note`` was loaded with, so a response
    rendered from the same instance shows what this request just wrote.
    """
    fundraise_details, _ = NoteFundraise.objects.update_or_create(
        note=note, defaults=values
    )
    note.fundraise_details = fundraise_details
