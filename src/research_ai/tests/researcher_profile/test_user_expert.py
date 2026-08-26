"""Tests for resolving a ResearchHub user to their Expert row."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from invite.models import NoteInvitation
from note.tests.helpers import create_note
from research_ai.models import Expert, GeneratedEmail
from research_ai.services.researcher_profile.user_expert import expert_for_user
from researchhub_access_group.constants import EDITOR


def _make_user(email="jane@researchhub_test.com"):
    return get_user_model().objects.create_user(
        username=email, password="password", email=email
    )


def _invite(recipient, expert_email, inviter=None):
    """An outreach email whose note invitation ``recipient`` holds."""
    inviter = inviter or _make_user(email=f"inviter+{expert_email}")
    note, _ = create_note(inviter, organization=None)
    invitation = NoteInvitation.create(
        recipient=recipient,
        recipient_email=expert_email,
        inviter=inviter,
        note=note,
        invite_type=EDITOR,
    )
    return GeneratedEmail.objects.create(
        created_by=inviter, expert_email=expert_email, note_invitation=invitation
    )


class ExpertForUserTests(TestCase):
    def test_prefers_registered_user_link_over_email(self):
        # Arrange
        user = _make_user()
        Expert.objects.create(email=user.email, first_name="ByEmail")
        linked = Expert.objects.create(
            email="other@example.com", first_name="Linked", registered_user=user
        )
        # Act & Assert
        self.assertEqual(expert_for_user(user), linked)

    def test_resolves_through_a_held_invitation_despite_different_email(self):
        # Arrange: invited at the institutional address, signed up with another.
        user = _make_user(email="jane.personal@researchhub_test.com")
        invited = Expert.objects.create(email="jane@stanford.edu", first_name="Invited")
        _invite(user, "jane@stanford.edu")
        # Act & Assert
        self.assertEqual(expert_for_user(user), invited)

    def test_invitation_chain_outranks_account_email(self):
        # Arrange
        user = _make_user()
        Expert.objects.create(email=user.email, first_name="ByEmail")
        invited = Expert.objects.create(email="jane@stanford.edu", first_name="Invited")
        _invite(user, "jane@stanford.edu")
        # Act & Assert
        self.assertEqual(expert_for_user(user), invited)

    def test_falls_back_to_account_email_case_insensitively(self):
        # Arrange
        user = _make_user()
        by_email = Expert.objects.create(email=user.email.upper(), first_name="ByEmail")
        # Act & Assert
        self.assertEqual(expert_for_user(user), by_email)

    def test_none_for_missing_email_or_row(self):
        # Arrange
        user = _make_user()
        no_email = _make_user(email="second@researchhub_test.com")
        no_email.email = ""
        # Act & Assert
        self.assertIsNone(expert_for_user(no_email))
        self.assertIsNone(expert_for_user(user))
