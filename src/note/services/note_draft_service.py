"""Draft Details writes for a notebook note.

Nothing here creates a live ``Grant``, ``Fundraise``, escrow, application, or
nonprofit link; those remain publish-time concerns.
"""

from hub.models import Hub
from note.models import GrantSettings, Note, PreregistrationSettings
from user.models import Author


def save_note_draft_details(
    note: Note,
    *,
    authors: list[Author] | None,
    hubs: list[Hub] | None,
    grant_settings: dict | None,
    preregistration_settings: dict | None,
) -> None:
    """Write every supplied relationship, leaving omitted ones untouched."""
    if authors is not None:
        note.reset_note_authors([author.id for author in authors])
    if hubs is not None:
        note.unified_document.hubs.set(hubs)
    if grant_settings is not None:
        _save_grant_settings(note, grant_settings)
    if preregistration_settings is not None:
        _save_preregistration_settings(note, preregistration_settings)


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
