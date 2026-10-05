from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from note.models import GrantSettings, Note
from note.tests.helpers import create_note
from purchase.models import Grant
from research_ai.services.note_tools import NoteToolset
from research_ai.services.notebook_chat.rfp_details_tools import (
    READ_RFP_DETAILS,
    UPDATE_RFP_DETAILS,
    RFPDetailsToolset,
)
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class RFPDetailsToolsetTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("rfp_details_user")
        self.user.first_name = "Ada"
        self.user.last_name = "Lovelace"
        self.user.save(update_fields=["first_name", "last_name"])
        self.colleague = create_random_authenticated_user("rfp_details_colleague")
        self.note, _ = create_note(self.user, organization=None)
        self.note.document_type = GRANT
        self.note.save(update_fields=["document_type"])
        self.permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )

    def _dispatch(self, tool, args, user=None):
        user = self.user if user is None else user
        notes = NoteToolset(user=user, note_ids={self.note.id})
        toolset = RFPDetailsToolset(
            user=user, get_note=notes.get_readable_note
        ).as_toolset()
        result, stop = toolset.dispatch(tool, args)
        self.assertFalse(stop)
        return result

    def _read(self, **kwargs):
        return self._dispatch(READ_RFP_DETAILS, {"note_id": self.note.id}, **kwargs)

    def _update(self, user=None, **fields):
        return self._dispatch(
            UPDATE_RFP_DETAILS, {"note_id": self.note.id, **fields}, user=user
        )

    def _settings(self):
        return GrantSettings.objects.get(note=self.note)

    def test_reads_an_unfilled_form(self):
        # Act
        result = self._read()

        # Assert
        self.assertEqual(
            result,
            {
                "note_id": self.note.id,
                "published": False,
                "amount": None,
                "currency": "USD",
                "organization": "",
                "description": "",
                "application_visibility": None,
                "contacts": [],
                "current_user": {"user_id": self.user.id, "name": "Ada Lovelace"},
            },
        )

    def test_reads_a_published_rfp_from_its_live_grant(self):
        # Arrange: publishing takes the terms from the request, not the draft.
        GrantSettings.objects.create(note=self.note, amount=1000, organization="Old")
        post = create_post(created_by=self.user, document_type=GRANT)
        post.note = self.note
        post.save(update_fields=["note"])
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            amount=75000,
            description="Funding for reproducible research.",
            application_visibility=Grant.APPLICATION_VISIBILITY_PRIVATE,
        )
        grant.contacts.set([self.colleague])

        # Act
        result = self._read()

        # Assert
        self.assertTrue(result["published"])
        self.assertEqual(result["amount"], "75000.00")
        self.assertEqual(result["organization"], "")
        self.assertEqual(result["description"], "Funding for reproducible research.")
        self.assertEqual(result["application_visibility"], "PRIVATE")
        self.assertEqual(
            [contact["user_id"] for contact in result["contacts"]],
            [self.colleague.id],
        )

    def test_bounds_a_long_description_entered_in_the_form(self):
        # Arrange: the note API does not cap what a user types into the form.
        GrantSettings.objects.create(note=self.note, description="x" * 5000)

        # Act
        result = self._read()

        # Assert
        self.assertEqual(len(result["description"]), 4000)
        self.assertTrue(result["description_is_truncated"])

    def test_sets_every_field_and_reads_them_back(self):
        # Act
        updated = self._update(
            amount=50000,
            organization="Research Foundation",
            description="Funding for reproducible neuroscience.",
            contact_user_ids=[self.user.id, self.colleague.id],
            application_visibility="PRIVATE",
        )
        read = self._read()

        # Assert
        settings = self._settings()
        self.assertEqual(settings.amount, Decimal("50000.00"))
        self.assertEqual(settings.currency, "USD")
        self.assertEqual(settings.organization, "Research Foundation")
        self.assertEqual(settings.description, "Funding for reproducible neuroscience.")
        self.assertEqual(
            settings.application_visibility, Grant.APPLICATION_VISIBILITY_PRIVATE
        )
        self.assertCountEqual(settings.contacts.all(), [self.user, self.colleague])
        self.assertTrue(updated.pop("saved"))
        self.assertEqual(updated, read)
        self.assertEqual(read["amount"], "50000.00")
        self.assertEqual(read["application_visibility"], "PRIVATE")
        self.assertCountEqual(
            [contact["user_id"] for contact in read["contacts"]],
            [self.user.id, self.colleague.id],
        )

    def test_changes_only_the_fields_passed(self):
        # Arrange
        self._update(amount=50000, organization="Research Foundation")

        # Act
        result = self._update(description="Funding for field surveys.")

        # Assert
        self.assertEqual(result["amount"], "50000.00")
        self.assertEqual(result["organization"], "Research Foundation")
        self.assertEqual(result["description"], "Funding for field surveys.")

    def test_null_arguments_leave_stored_values_alone(self):
        # Arrange: models pad optional arguments with nulls.
        self._update(
            amount=50000,
            organization="Research Foundation",
            contact_user_ids=[self.user.id],
        )

        # Act
        result = self._update(
            amount=None,
            organization=None,
            contact_user_ids=None,
            application_visibility=None,
            description="Funding for field surveys.",
        )

        # Assert
        self.assertEqual(result["amount"], "50000.00")
        self.assertEqual(result["organization"], "Research Foundation")
        self.assertEqual(
            [contact["user_id"] for contact in result["contacts"]], [self.user.id]
        )

    def test_empty_values_clear_text_and_contacts(self):
        # Arrange
        self._update(organization="Foundation", contact_user_ids=[self.user.id])

        # Act
        result = self._update(organization="", contact_user_ids=[])

        # Assert
        self.assertEqual(result["organization"], "")
        self.assertEqual(result["contacts"], [])

    def test_replaces_the_contacts(self):
        # Arrange
        self._update(contact_user_ids=[self.user.id])

        # Act
        result = self._update(contact_user_ids=[self.colleague.id, self.colleague.id])

        # Assert
        self.assertEqual(
            [contact["user_id"] for contact in result["contacts"]],
            [self.colleague.id],
        )

    def test_rejects_an_amount_that_is_not_a_positive_number(self):
        for amount in (0, -100, "lots", True, 10.999, float("nan")):
            with self.subTest(amount=amount):
                # Act
                result = self._update(amount=amount)

                # Assert
                self.assertIn("amount", result["error"])
                self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_rejects_contacts_that_are_not_existing_user_ids(self):
        # Arrange: 1.9 must not be coerced into user 1.
        missing_id = self.colleague.id + 1000

        for contact_user_ids in ([missing_id], [1.9], [True], "all", [None]):
            with self.subTest(contact_user_ids=contact_user_ids):
                # Act
                result = self._update(contact_user_ids=contact_user_ids)

                # Assert
                self.assertIn("contact_user_ids", result["error"])
                self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_accepts_a_contact_id_sent_as_a_digit_string(self):
        # Act
        result = self._update(contact_user_ids=[f" {self.colleague.id} "])

        # Assert
        self.assertEqual(
            [contact["user_id"] for contact in result["contacts"]],
            [self.colleague.id],
        )

    def test_accepts_visibility_in_any_case_and_rejects_unknown_values(self):
        # Act
        accepted = self._update(application_visibility="public")
        rejected = self._update(application_visibility="")

        # Assert
        self.assertEqual(accepted["application_visibility"], "PUBLIC")
        self.assertEqual(
            rejected["error"],
            "application_visibility must be one of OPTIONAL, PRIVATE, PUBLIC",
        )
        self.assertEqual(self._settings().application_visibility, "PUBLIC")

    def test_rejects_an_oversized_description(self):
        # Act
        result = self._update(description="x" * 4001)

        # Assert
        self.assertIn("description must be at most 4000 characters", result["error"])
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_requires_at_least_one_field(self):
        # Act
        result = self._update()

        # Assert
        self.assertIn("pass at least one Details field", result["error"])

    def test_refuses_a_note_that_is_not_an_rfp(self):
        # Arrange
        self.note.document_type = PREREGISTRATION
        self.note.save(update_fields=["document_type"])

        # Act
        read = self._read()
        updated = self._update(amount=50000)

        # Assert
        expected = {
            "error": (
                f"note {self.note.id} is not an RFP (GRANT) note; only an RFP "
                "has a Details form"
            )
        }
        self.assertEqual(read, expected)
        self.assertEqual(updated, expected)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_viewer_can_read_but_not_update(self):
        # Arrange
        self.permission.access_type = VIEWER
        self.permission.save(update_fields=["access_type"])

        # Act
        read = self._read()
        updated = self._update(amount=50000)

        # Assert
        self.assertEqual(read["note_id"], self.note.id)
        self.assertEqual(
            updated, {"error": f"no edit permission on note {self.note.id}"}
        )
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_refuses_a_published_rfp(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=GRANT)
        post.note = self.note
        post.save(update_fields=["note"])

        # Act
        result = self._update(amount=50000)

        # Assert
        self.assertEqual(result["error"], "Published notes cannot change RFP details.")
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_refuses_a_note_the_caller_cannot_reach(self):
        # Arrange
        expected = {"error": f"note {self.note.id} not found or not accessible"}

        for user in (self.colleague, AnonymousUser()):
            with self.subTest(user=user):
                # Act
                read = self._read(user=user)
                updated = self._update(user=user, amount=50000)

                # Assert
                self.assertEqual(read, expected)
                self.assertEqual(updated, expected)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_notifies_the_notebook_that_the_note_changed(self):
        # Arrange: a Details write adds no NoteContent for the client to see.
        self.note.organization = self.user.organization
        self.note.save(update_fields=["organization"])

        # Act
        with patch.object(Note, "notify_note_updated_title") as notify:
            result = self._update(amount=50000)

        # Assert
        self.assertTrue(result["saved"])
        notify.assert_called_once_with()

    def test_keeps_the_write_when_the_notebook_push_fails(self):
        # Arrange
        self.note.organization = self.user.organization
        self.note.save(update_fields=["organization"])

        # Act
        with patch.object(
            Note, "notify_note_updated_title", side_effect=RuntimeError("down")
        ):
            result = self._update(amount=50000)

        # Assert
        self.assertTrue(result["saved"])
        self.assertEqual(self._settings().amount, 50000)

    def test_reports_an_unexpected_failure_without_raising(self):
        # Arrange
        toolset = RFPDetailsToolset(
            user=self.user, get_note=Mock(side_effect=RuntimeError("database down"))
        ).as_toolset()

        # Act
        read, _stop = toolset.dispatch(READ_RFP_DETAILS, {"note_id": self.note.id})
        updated, _stop = toolset.dispatch(
            UPDATE_RFP_DETAILS, {"note_id": self.note.id, "amount": 50000}
        )

        # Assert
        self.assertEqual(
            updated, {"error": "updating RFP details is temporarily unavailable"}
        )
        self.assertEqual(read, {"error": "RFP details are temporarily unavailable"})
