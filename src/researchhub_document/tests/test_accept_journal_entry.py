from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from note.models import Note
from purchase.models import Fundraise
from reputation.models import Escrow
from researchhub_access_group.constants import ADMIN, NO_ACCESS
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    NOTE,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_random_default_user


class AcceptJournalEntryTests(APITestCase):
    accept_url = "/api/researchhubpost/accept_journal_entry/"

    def setUp(self) -> None:
        """Create users and authenticate the journal entry owner."""
        self.user = create_random_default_user("journal_entry_owner")
        self.other_user = create_random_default_user("journal_entry_other")
        self.hub = create_hub("journal entry hub")
        self.journey_service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_accept_journal_entry_creates_registered_report_note(self) -> None:
        """Verify accepting a funded proposal creates an unpublished report note."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id=response.data["id"])
        proposal.refresh_from_db()
        self.assertEqual(note.created_by, self.user)
        self.assertEqual(note.document_type, REGISTERED_REPORT)
        self.assertEqual(note.unified_document.document_type, NOTE)
        self.assertEqual(note.latest_version.plain_text, proposal.renderable_text)
        self.assertEqual(response.data["access"], "PRIVATE")
        self.assertEqual(response.data["fundraise_id"], fundraise.id)
        self.assertEqual(response.data["journey_id"], proposal.journey_id)
        self.assertEqual(response.data["proposal_id"], proposal.id)
        self.assertIsNone(response.data["post"])
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )
        self.assertCountEqual(
            note.unified_document.hubs.all(),
            proposal.unified_document.hubs.all(),
        )
        self.assertTrue(proposal.journey.is_in_journal)

    def test_accept_journal_entry_creates_private_permissions(self) -> None:
        """Verify accepting a journal entry creates private note permissions."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        note = Note.objects.get(id=response.data["id"])
        permissions = note.unified_document.permissions
        self.assertTrue(
            permissions.filter(
                access_type=ADMIN,
                user=self.user,
                organization__isnull=True,
            ).exists()
        )
        self.assertTrue(
            permissions.filter(
                access_type=NO_ACCESS,
                user=self.user,
                organization=self.user.organization,
            ).exists()
        )

    def test_accept_journal_entry_rejects_other_users_fundraise(self) -> None:
        """Verify users cannot accept fundraises they do not own."""
        # Arrange
        proposal = self._create_proposal(self.other_user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_accept_journal_entry_rejects_open_fundraise(self) -> None:
        """Verify open fundraises cannot create registered report notes."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.OPEN, Decimal(100))

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_accept_journal_entry_rejects_unfunded_fundraise(self) -> None:
        """Verify completed fundraises need funding before note creation."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(0))

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_accept_journal_entry_rejects_reported_fundraise(self) -> None:
        """Verify fundraises with registered reports cannot create another note."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))
        self.journey_service.include_completed_fundraise_in_journal(fundraise)
        proposal.refresh_from_db()
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Existing registered report",
        )
        self.journey_service.attach_stage(proposal.journey, report)

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def test_accept_journal_entry_requires_authentication(self) -> None:
        """Verify anonymous users cannot accept journal entries."""
        # Arrange
        proposal = self._create_proposal(self.user)
        fundraise = self._create_fundraise(proposal, Fundraise.COMPLETED, Decimal(100))
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            self._build_accept_url(self.user.id, fundraise.id),
        )

        # Assert
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(
            Note.objects.filter(document_type=REGISTERED_REPORT).count(),
            0,
        )

    def _build_accept_url(self, user_id: int, fundraise_id: int) -> str:
        """Build the journal entry acceptance URL."""
        return f"{self.accept_url}?user_id={user_id}&fundraise_id={fundraise_id}"

    def _create_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal post with journal context."""
        proposal = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            renderable_text="Proposal content ready for registered report drafting.",
            title=f"{user.username} proposal title",
        )
        proposal.unified_document.hubs.add(self.hub)
        return proposal

    def _create_fundraise(
        self, proposal: ResearchhubPost, status: str, amount: Decimal
    ) -> Fundraise:
        """Create a fundraise with an escrowed funding amount."""
        fundraise = Fundraise.objects.create(
            created_by=proposal.created_by,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=status,
        )
        fundraise.escrow = Escrow.objects.create(
            created_by=proposal.created_by,
            content_type=ContentType.objects.get_for_model(Fundraise),
            object_id=fundraise.id,
            hold_type=Escrow.FUNDRAISE,
            amount_holding=amount,
        )
        fundraise.save(update_fields=["escrow"])
        return fundraise
