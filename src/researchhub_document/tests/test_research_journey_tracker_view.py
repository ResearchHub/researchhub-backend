from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchJourney, ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.constants.journey_stage import (
    JOURNEY_STAGE_GRANT,
    JOURNEY_STAGE_PROPOSAL,
    JOURNEY_STAGE_REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.models import User
from user.tests.helpers import create_random_default_user


class ResearchJourneyTrackerViewSetTests(APITestCase):
    def setUp(self) -> None:
        """Create users and a journey service for tracker endpoint tests."""
        self.user = create_random_default_user("journey_view_user")
        self.other_user = create_random_default_user("journey_view_other_user")
        self.service = JourneyService()
        self.client.force_authenticate(self.user)

    def test_return_tracker_with_stage_detail_urls(self) -> None:
        """Verify the tracker returns stage metadata and detail URLs."""
        # Arrange
        journey, grant, proposal = self.create_grant_proposal_journey()
        report = self.create_registered_report(journey)

        # Act
        response = self.client.get(self.build_url(journey))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["latest_stage"], JOURNEY_STAGE_REGISTERED_REPORT)
        stages = {stage["stage"]: stage for stage in response.data["stages"]}
        self.assertEqual(
            list(stages.keys()),
            [
                JOURNEY_STAGE_GRANT,
                JOURNEY_STAGE_PROPOSAL,
                JOURNEY_STAGE_REGISTERED_REPORT,
            ],
        )
        self.assertEqual(stages[JOURNEY_STAGE_GRANT]["status"], "completed")
        self.assertEqual(
            stages[JOURNEY_STAGE_GRANT]["work"]["detail_url"],
            f"/api/grant/{grant.id}/",
        )
        self.assertEqual(stages[JOURNEY_STAGE_PROPOSAL]["status"], "completed")
        self.assertEqual(
            stages[JOURNEY_STAGE_PROPOSAL]["work"]["detail_url"],
            f"/api/researchhubpost/{proposal.id}/",
        )
        self.assertEqual(stages[JOURNEY_STAGE_REGISTERED_REPORT]["status"], "current")
        self.assertEqual(
            stages[JOURNEY_STAGE_REGISTERED_REPORT]["work"]["detail_url"],
            f"/api/researchhubpost/{report.id}/",
        )

    def test_return_pending_report_stage(self) -> None:
        """Verify the tracker returns a pending registered report step."""
        # Arrange
        journey, _, proposal = self.create_grant_proposal_journey()

        # Act
        response = self.client.get(self.build_url(journey))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["latest_stage"], JOURNEY_STAGE_PROPOSAL)
        stages = {stage["stage"]: stage for stage in response.data["stages"]}
        self.assertEqual(stages[JOURNEY_STAGE_PROPOSAL]["status"], "current")
        self.assertEqual(
            stages[JOURNEY_STAGE_REGISTERED_REPORT]["status"],
            "pending",
        )
        self.assertIsNone(stages[JOURNEY_STAGE_REGISTERED_REPORT]["work"])
        self.assertEqual(
            stages[JOURNEY_STAGE_PROPOSAL]["work"]["detail_url"],
            f"/api/researchhubpost/{proposal.id}/",
        )

    def test_hide_private_journey_from_unrelated_viewer(self) -> None:
        """Verify private journey stages do not expose a tracker."""
        # Arrange
        proposal = self.create_proposal(self.other_user)
        proposal.unified_document.is_public = False
        proposal.unified_document.save(update_fields=["is_public"])
        journey = self.service.get_or_create_for_preregistration(proposal)
        self.client.force_authenticate(self.user)

        # Act
        response = self.client.get(self.build_url(journey))

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def build_url(self, journey: ResearchJourney) -> str:
        """Build the research journey tracker detail URL."""
        return f"/api/research_journey_tracker/{journey.id}/"

    def create_grant_proposal_journey(
        self,
    ) -> tuple[ResearchJourney, Grant, ResearchhubPost]:
        """Create a journey with a visible grant and proposal."""
        grant, _ = self.create_grant_with_post()
        proposal = self.create_proposal(self.user)
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=self.user,
        )
        journey = self.service.get_or_create_for_preregistration(proposal)
        return journey, grant, proposal

    def create_grant_with_post(self) -> tuple[Grant, ResearchhubPost]:
        """Create an open grant backed by a grant post."""
        grant_post = create_post(
            created_by=self.user,
            document_type=GRANT,
            title="Journey grant title",
        )
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Journey Grant",
            description="Grant for journey tracker tests.",
            status=Grant.OPEN,
        )
        return grant, grant_post

    def create_proposal(self, user: User) -> ResearchhubPost:
        """Create a proposal post for a journey."""
        return create_post(
            created_by=user,
            document_type=PREREGISTRATION,
            title=f"{user.id} journey proposal",
        )

    def create_registered_report(self, journey: ResearchJourney) -> ResearchhubPost:
        """Create and attach a registered report to a journey."""
        report = create_post(
            created_by=self.user,
            document_type=REGISTERED_REPORT,
            title="Journey registered report",
        )
        self.service.attach_stage(journey, report)
        return report
