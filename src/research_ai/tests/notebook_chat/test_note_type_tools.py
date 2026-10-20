from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from note.models import GrantSettings, Note
from note.tests.helpers import create_note
from purchase.models import Grant
from research_ai.services.notebook_chat.note_type_tools import (
    CHANGE_NOTE_TYPE,
    NoteTypeToolset,
)
from researchhub_access_group.constants import ADMIN, VIEWER
from researchhub_access_group.models import Permission
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_authenticated_user


class NoteTypeToolsetTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("note_type_user")
        self.note, _ = create_note(self.user, organization=None)
        self._set_type(GRANT)
        self.permission = Permission.objects.create(
            access_type=ADMIN,
            content_type=ContentType.objects.get_for_model(ResearchhubUnifiedDocument),
            object_id=self.note.unified_document_id,
            user=self.user,
        )

    def _set_type(self, document_type):
        self.note.document_type = document_type
        self.note.save(update_fields=["document_type"])

    def _change(self, asking=False, **args):
        toolset = NoteTypeToolset(
            note=self.note, user=self.user, asking=asking
        ).as_toolset()
        result, stop = toolset.dispatch(CHANGE_NOTE_TYPE, args)
        self.assertFalse(stop)
        self.note.refresh_from_db()
        return result

    def _grant(self):
        post = create_post(created_by=self.user, document_type=GRANT, title="Sleep RFP")
        return Grant.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            amount=Decimal("75000.00"),
            currency="USD",
            status=Grant.OPEN,
            end_date=timezone.now() + timedelta(days=30),
        )

    def test_switches_an_rfp_to_a_proposal(self):
        # Act
        result = self._change(document_type=PREREGISTRATION)

        # Assert
        self.assertEqual(self.note.document_type, PREREGISTRATION)
        self.assertEqual(result["document_type"], PREREGISTRATION)
        self.assertEqual(result["previous_document_type"], GRANT)
        self.assertIn("search_grants", result["next_steps"])
        self.assertNotIn("rfp_details", result)

    def test_switches_a_proposal_to_an_rfp_and_fills_in_its_details(self):
        # Arrange
        self._set_type(PREREGISTRATION)

        # Act
        result = self._change(
            document_type=GRANT,
            rfp_details={
                "description": "Funds pilot trials of home BP monitoring.",
                "amount": None,
            },
        )

        # Assert
        self.assertEqual(self.note.document_type, GRANT)
        settings = GrantSettings.objects.get(note=self.note)
        self.assertEqual(
            settings.description, "Funds pilot trials of home BP monitoring."
        )
        self.assertIsNone(settings.amount)
        self.assertEqual(
            result["rfp_details"]["description"],
            "Funds pilot trials of home BP monitoring.",
        )
        self.assertIsNone(result["rfp_details"]["amount"])

    def test_leaving_a_proposal_clears_its_selected_rfp(self):
        # Arrange
        self._set_type(PREREGISTRATION)
        grant = self._grant()
        self.note.selected_grant = grant
        self.note.save(update_fields=["selected_grant"])

        # Act
        result = self._change(document_type=GRANT)

        # Assert
        self.assertEqual(self.note.document_type, GRANT)
        self.assertIsNone(self.note.selected_grant_id)
        self.assertEqual(
            result["cleared_selected_rfp"],
            {"grant_id": grant.id, "title": "Sleep RFP"},
        )

    def test_refuses_while_the_user_has_not_answered(self):
        # Act
        result = self._change(asking=True, document_type=PREREGISTRATION)

        # Assert
        self.assertIn("has not answered", result["error"])
        self.assertEqual(self.note.document_type, GRANT)

    def test_invalid_details_leave_the_type_unchanged(self):
        # Arrange
        self._set_type(PREREGISTRATION)

        # Act
        result = self._change(document_type=GRANT, rfp_details={"amount": 0})

        # Assert
        self.assertEqual(result, {"error": "amount must be greater than 0"})
        self.assertEqual(self.note.document_type, PREREGISTRATION)
        self.assertFalse(GrantSettings.objects.filter(note=self.note).exists())

    def test_refuses_details_when_switching_to_a_proposal(self):
        # Act
        result = self._change(
            document_type=PREREGISTRATION, rfp_details={"amount": 5000}
        )

        # Assert
        self.assertEqual(
            result, {"error": "rfp_details applies only when switching to GRANT"}
        )
        self.assertEqual(self.note.document_type, GRANT)

    def test_switches_only_between_an_rfp_and_a_proposal(self):
        cases = (
            (GRANT, GRANT, "the note is already an RFP"),
            (DISCUSSION, GRANT, "only an RFP or a proposal note can switch"),
            (GRANT, DISCUSSION, "document_type must be GRANT or PREREGISTRATION"),
        )
        for current, target, error in cases:
            with self.subTest(current=current, target=target):
                # Arrange
                self._set_type(current)

                # Act
                result = self._change(document_type=target)

                # Assert
                self.assertIn(error, result["error"])
                self.assertEqual(self.note.document_type, current)

    def test_a_viewer_cannot_switch(self):
        # Arrange
        self.permission.access_type = VIEWER
        self.permission.save(update_fields=["access_type"])

        # Act
        result = self._change(document_type=PREREGISTRATION)

        # Assert
        self.assertEqual(
            result, {"error": f"no edit permission on note {self.note.id}"}
        )
        self.assertEqual(self.note.document_type, GRANT)

    def test_refuses_a_published_note(self):
        # Arrange
        post = create_post(created_by=self.user, document_type=GRANT)
        post.note = self.note
        post.save(update_fields=["note"])

        # Act
        result = self._change(document_type=PREREGISTRATION)

        # Assert
        self.assertEqual(result, {"error": "a published note cannot change type"})
        self.assertEqual(self.note.document_type, GRANT)

    def test_notifies_the_notebook_that_the_note_changed(self):
        # Arrange
        self.note.organization = self.user.organization
        self.note.save(update_fields=["organization"])

        # Act
        with patch.object(Note, "notify_note_updated_title") as notify:
            self._change(document_type=PREREGISTRATION)

        # Assert
        notify.assert_called_once_with()
