from decimal import Decimal

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Fundraise
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.tests.helpers import create_random_default_user


class JournalV2FeedViewSetTests(APITestCase):
    def setUp(self) -> None:
        """Create the user, client, and service used by journal feed tests."""
        self.user = create_random_default_user("journal_v2_user")
        self.service = JourneyService()
        self.url = reverse("journal_v2_feed-list")
        self.client.force_authenticate(self.user)

    def test_list_includes_journal_proposals(self) -> None:
        """Verify the feed includes proposals from journeys in the journal."""
        # Arrange
        proposal = self.create_completed_proposal("Included proposal")
        excluded_proposal = self.create_completed_proposal(
            "Excluded proposal",
            include_in_journal=False,
        )

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertIn(proposal.id, post_ids)
        self.assertNotIn(excluded_proposal.id, post_ids)

    def test_list_prefers_registered_reports(self) -> None:
        """Verify the feed shows the registered report when a journey has one."""
        # Arrange
        proposal = self.create_completed_proposal("Reported proposal")
        report = self.create_registered_report(proposal, "Registered report")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertIn(report.id, post_ids)
        self.assertNotIn(proposal.id, post_ids)

    def test_list_returns_one_card_per_journey(self) -> None:
        """Verify each journal journey contributes only its latest stage card."""
        # Arrange
        proposal = self.create_completed_proposal("Proposal only")
        reported_proposal = self.create_completed_proposal("Proposal with report")
        report = self.create_registered_report(reported_proposal, "Latest report")

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        post_ids = self.get_response_post_ids(response.data)
        self.assertEqual(post_ids.count(proposal.id), 1)
        self.assertEqual(post_ids.count(report.id), 1)
        self.assertNotIn(reported_proposal.id, post_ids)
        self.assertEqual(len(post_ids), 2)

    def create_completed_proposal(
        self, title: str, include_in_journal: bool = True
    ) -> ResearchhubPost:
        """Create an approved proposal with a completed fundraise and journey."""
        proposal = create_post(
            created_by=self.user,
            document_type=PREREGISTRATION,
            title=title,
        )
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        if include_in_journal:
            self.service.include_completed_fundraise_in_journal(fundraise)
        else:
            self.service.ensure_approved_preregistration_has_journey(proposal)

        proposal.refresh_from_db()
        return proposal

    def create_registered_report(
        self, proposal: ResearchhubPost, title: str
    ) -> ResearchhubPost:
        """Create and attach a registered report to a proposal journey."""
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title=title,
        )
        self.service.attach_stage(proposal.journey, report)
        return report

    @staticmethod
    def get_response_post_ids(data: dict) -> list[int]:
        """Return post ids from a paginated journal feed response."""
        return [item["content_object"]["id"] for item in data["results"]]
