from decimal import Decimal

from django.test import TestCase

from note.models import GrantSettings
from note.services.note_draft_service import (
    NOT_RFP_NOTE,
    NOTE_PUBLISHED,
    DraftDetailsError,
    update_grant_settings,
)
from note.tests.helpers import create_note
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class UpdateGrantSettingsTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("draft_details_user")
        self.note, _ = create_note(self.user, organization=None)
        self.note.document_type = GRANT
        self.note.save(update_fields=["document_type"])

    def test_writes_the_supplied_fields_and_keeps_the_rest(self):
        # Arrange
        update_grant_settings(
            note=self.note,
            values={"amount": Decimal(50000), "contacts": [self.user]},
        )

        # Act
        settings = update_grant_settings(
            note=self.note, values={"organization": "Research Foundation"}
        )

        # Assert
        settings.refresh_from_db()
        self.assertEqual(settings.amount, Decimal("50000.00"))
        self.assertEqual(settings.organization, "Research Foundation")
        self.assertEqual(list(settings.contacts.all()), [self.user])
        self.assertEqual(self.note.grant_settings, settings)

    def test_leaves_the_caller_values_intact(self):
        # Arrange
        values = {"amount": Decimal(50000), "contacts": [self.user]}

        # Act
        update_grant_settings(note=self.note, values=values)

        # Assert
        self.assertEqual(values, {"amount": Decimal(50000), "contacts": [self.user]})

    def test_refuses_a_note_that_is_not_an_rfp(self):
        # Arrange
        self.note.document_type = PREREGISTRATION
        self.note.save(update_fields=["document_type"])

        # Act
        with self.assertRaises(DraftDetailsError) as raised:
            update_grant_settings(note=self.note, values={"organization": "Org"})

        # Assert
        self.assertEqual(str(raised.exception), NOT_RFP_NOTE)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_refuses_a_published_note(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=GRANT)
        post.note = self.note
        post.save(update_fields=["note"])

        # Act
        with self.assertRaises(DraftDetailsError) as raised:
            update_grant_settings(note=self.note, values={"organization": "Org"})

        # Assert
        self.assertEqual(str(raised.exception), NOTE_PUBLISHED)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_refuses_a_note_published_after_the_caller_loaded_it(self):
        # Arrange: the caller's instance has already cached "no post".
        self.assertFalse(hasattr(self.note, "post"))
        post = create_post(created_by=self.user, document_type=GRANT)
        post.note_id = self.note.id
        post.save(update_fields=["note"])

        # Act
        with self.assertRaises(DraftDetailsError) as raised:
            update_grant_settings(note=self.note, values={"organization": "Org"})

        # Assert
        self.assertEqual(str(raised.exception), NOTE_PUBLISHED)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())
