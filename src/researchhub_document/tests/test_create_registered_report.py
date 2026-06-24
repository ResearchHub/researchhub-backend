from decimal import Decimal

from rest_framework.test import APITestCase

from hub.tests.helpers import create_hub
from note.tests.helpers import create_note
from purchase.models import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost, ResearchhubUnifiedDocument
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_organization, create_random_default_user


class CreateRegisteredReportTests(APITestCase):
    create_url = "/api/researchhubpost/"

    def setUp(self) -> None:
        """Create users and proposal context for registered report tests."""
        self.user = create_random_default_user("rr_owner")
        self.moderator = create_random_default_user("rr_moderator", moderator=True)
        self.hub = create_hub("registered report hub")
        self.organization = create_organization(
            name="Registered Report Org",
            slug="registered-report-org",
        )
        self.service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_create_report_attaches_proposal(self) -> None:
        """Verify a completed proposal owner can create a registered report."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        note, _ = create_note(self.user, self.organization)
        payload = self._build_payload(proposal, note_id=note.id)

        # Act
        response = self.client.post(self.create_url, payload, format="json")

        # Assert
        self.assertEqual(response.status_code, 200)
        report = ResearchhubPost.objects.get(id=response.data["id"])
        proposal.refresh_from_db()
        self.assertEqual(report.document_type, REGISTERED_REPORT)
        self.assertEqual(report.created_by, self.user)
        self.assertEqual(report.note_id, note.id)
        self.assertEqual(report.journey, proposal.journey)
        self.assertEqual(self.service.get_registered_report(proposal.journey), report)
        self.assertEqual(
            report.unified_document.status,
            ResearchhubUnifiedDocument.APPROVED,
        )
        self.assertTrue(report.unified_document.is_public)
        self.assertCountEqual(report.authors.all(), proposal.authors.all())
        self.assertCountEqual(
            report.unified_document.hubs.all(),
            proposal.unified_document.hubs.all(),
        )

    def test_reject_moderator_for_other_owner(self) -> None:
        """Verify moderators cannot create reports for another user's proposal."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_open_proposal(self) -> None:
        """Verify proposals without completed fundraises cannot create reports."""
        # Arrange
        proposal = self._create_open_proposal(self.user)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).exists()
        )

    def test_reject_reported_proposal(self) -> None:
        """Verify proposals with registered reports cannot create another one."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Existing registered report",
        )
        self.service.attach_stage(proposal.journey, report)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            ResearchhubPost.objects.filter(document_type=REGISTERED_REPORT).count(),
            1,
        )

    def test_require_login(self) -> None:
        """Verify anonymous users cannot create registered reports."""
        # Arrange
        proposal = self._create_completed_proposal(self.user)
        self.client.force_authenticate(None)

        # Act
        response = self.client.post(
            self.create_url,
            self._build_payload(proposal),
            format="json",
        )

        # Assert
        self.assertIn(response.status_code, (401, 403))

    def _build_payload(
        self, proposal: ResearchhubPost, **overrides: object
    ) -> dict[str, object]:
        """Build a valid registered report request payload."""
        payload = {
            "document_type": REGISTERED_REPORT,
            "proposal_id": proposal.id,
            "title": "Registered report title",
            "renderable_text": (
                "Registered report body. Registered report body. "
                "Registered report body."
            ),
            "full_src": "# Registered report",
        }
        payload.update(overrides)
        return payload

    def _create_completed_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal with a completed fundraise."""
        proposal = self._create_proposal(user)
        fundraise = Fundraise.objects.create(
            created_by=user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )
        self.service.include_completed_fundraise_in_journal(fundraise)
        proposal.refresh_from_db()
        return proposal

    def _create_open_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved proposal with an open fundraise."""
        proposal = self._create_proposal(user)
        Fundraise.objects.create(
            created_by=user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )
        self.service.ensure_approved_preregistration_has_journey(proposal)
        proposal.refresh_from_db()
        return proposal

    def _create_proposal(self, user: User) -> ResearchhubPost:
        """Create an approved preregistration with copied report context."""
        proposal = create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title=f"{user.id} proposal title",
        )
        proposal.authors.add(user.author_profile)
        proposal.unified_document.hubs.add(self.hub)
        return proposal
