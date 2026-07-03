from decimal import Decimal

from django.core.files.storage import default_storage
from rest_framework.test import APITestCase

from purchase.models import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_random_default_user


class ListCompletedProposalTests(APITestCase):
    candidate_url = "/api/researchhubpost/list-completed-proposals/"

    def setUp(self) -> None:
        """Create users and authenticate the proposal owner."""
        self.user = create_random_default_user("funded_candidate_owner")
        self.other_user = create_random_default_user("funded_candidate_other")
        self.service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_list_completed_proposals_returns_candidate(self) -> None:
        """Verify the popup endpoint returns the user's completed proposal."""
        # Arrange
        proposal = self._create_funded_proposal(self.user)
        proposal.image = "proposal-image.png"
        proposal.save(update_fields=["image"])

        # Act
        response = self.client.get(self.candidate_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        candidate_ids = [item["id"] for item in response.data]
        self.assertEqual(candidate_ids, [proposal.id])
        self.assertEqual(
            response.data[0]["image_url"],
            default_storage.url(proposal.image),
        )
        self.assertEqual(
            response.data[0]["completed_fundraise"]["status"],
            Fundraise.COMPLETED,
        )

    def test_list_completed_proposals_excludes_other_authors(self) -> None:
        """Verify the popup endpoint excludes completed proposals by other users."""
        # Arrange
        self._create_funded_proposal(self.other_user)

        # Act
        response = self.client.get(self.candidate_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_list_completed_proposals_excludes_ineligible_proposals(self) -> None:
        """Verify open fundraises and reported journeys are excluded."""
        # Arrange
        candidate = self._create_funded_proposal(self.user)
        open_proposal = self._create_open_proposal(self.user)
        reported_proposal = self._create_funded_proposal(self.user)
        registered_report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Registered report title",
        )
        self.service.attach_stage(reported_proposal.journey, registered_report)

        # Act
        response = self.client.get(self.candidate_url)

        # Assert
        self.assertEqual(response.status_code, 200)
        candidate_ids = [item["id"] for item in response.data]
        self.assertEqual(candidate_ids, [candidate.id])
        self.assertNotIn(open_proposal.id, candidate_ids)
        self.assertNotIn(reported_proposal.id, candidate_ids)

    def test_list_completed_proposals_requires_authentication(self) -> None:
        """Verify anonymous users cannot list completed proposal candidates."""
        # Arrange
        self._create_funded_proposal(self.user)
        self.client.force_authenticate(None)

        # Act
        response = self.client.get(self.candidate_url)

        # Assert
        self.assertIn(response.status_code, (401, 403))

    def _create_funded_proposal(self, user: User) -> ResearchhubPost:
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
        """Create an approved preregistration post."""
        return create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title=f"{user.username} proposal title",
        )
