from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError
from django.test import TestCase

from purchase.models import Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubUnifiedDocument, ResearchJourney
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.related_models.researchhub_post_model import (
    JOURNAL_STAGE_GRANT,
    JOURNAL_STAGE_PROPOSAL,
    JOURNAL_STAGE_REGISTERED_REPORT,
)
from researchhub_document.services.journey_service import JourneyService
from user.tests.helpers import create_random_default_user


class JourneyServiceTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("journey_author")
        self.service = JourneyService()

    def test_get_or_create_for_preregistration_creates_journey(self):
        # Arrange
        proposal = self._post(PREREGISTRATION)

        # Act
        journey = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        proposal.refresh_from_db()
        self.assertEqual(journey.created_by, self.user)
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)

    def test_get_or_create_for_preregistration_is_idempotent(self):
        # Arrange
        proposal = self._post(PREREGISTRATION)

        # Act
        first = self.service.get_or_create_for_preregistration(proposal)
        second = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        self.assertEqual(first, second)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_get_or_create_for_preregistration_uses_grant_application(self):
        # Arrange
        proposal = self._post(PREREGISTRATION)
        grant = self._grant()
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=self.user,
        )

        # Act
        journey = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        self.assertEqual(journey.grant, grant)

    def test_get_or_create_for_preregistration_rejects_non_preregistration(self):
        # Arrange
        post = self._post(DISCUSSION)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.get_or_create_for_preregistration(post)

    def test_attach_stage_attaches_registered_report(self):
        # Arrange
        journey = self._journey()
        registered_report = self._post(REGISTERED_REPORT)

        # Act
        self.service.attach_stage(journey, registered_report)

        # Assert
        registered_report.refresh_from_db()
        self.assertEqual(registered_report.journey, journey)

    def test_attach_stage_attaches_proposal_to_empty_journey(self):
        # Arrange
        journey = ResearchJourney.objects.create(created_by=self.user)
        proposal = self._post(PREREGISTRATION)

        # Act
        self.service.attach_stage(journey, proposal)

        # Assert
        journey.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)

    def test_attach_stage_rejects_registered_report_without_proposal(self):
        # Arrange
        journey = ResearchJourney.objects.create(created_by=self.user)
        registered_report = self._post(REGISTERED_REPORT)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, registered_report)

    def test_attach_stage_rejects_second_registered_report(self):
        # Arrange
        journey = self._journey()
        first_report = self._post(REGISTERED_REPORT)
        second_report = self._post(REGISTERED_REPORT)
        self.service.attach_stage(journey, first_report)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, second_report)

    def test_attach_stage_normalizes_registered_report_integrity_error(self):
        # Arrange
        journey = self._journey()
        registered_report = self._post(REGISTERED_REPORT)

        # Act / Assert
        with patch.object(
            registered_report,
            "save",
            side_effect=IntegrityError("duplicate registered report"),
        ):
            with self.assertRaises(ValueError):
                self.service.attach_stage(journey, registered_report)

    def test_attach_stage_rejects_second_proposal(self):
        # Arrange
        journey = ResearchJourney.objects.create(created_by=self.user)
        first_proposal = self._post(PREREGISTRATION)
        second_proposal = self._post(PREREGISTRATION)
        first_proposal.journey = journey
        first_proposal.save(update_fields=["journey"])

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, second_proposal)

    def test_attach_stage_rejects_reassignment(self):
        # Arrange
        first_journey = self._journey()
        second_journey = self._journey()
        registered_report = self._post(REGISTERED_REPORT)
        self.service.attach_stage(first_journey, registered_report)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(second_journey, registered_report)

    def test_latest_stage_post_returns_registered_report_when_present(self):
        # Arrange
        journey = self._journey()
        registered_report = self._post(REGISTERED_REPORT)

        # Act / Assert
        self.assertEqual(
            self.service.latest_stage_post(journey),
            journey.preregistration_post,
        )
        self.assertFalse(self.service.has_registered_report(journey))

        self.service.attach_stage(journey, registered_report)
        self.assertEqual(self.service.latest_stage_post(journey), registered_report)
        self.assertTrue(self.service.has_registered_report(journey))

    def test_stages_returns_grant_proposal_and_registered_report(self):
        # Arrange
        proposal = self._post(PREREGISTRATION)
        grant = self._grant()
        journey = ResearchJourney.objects.create(
            created_by=self.user,
            grant=grant,
            preregistration_post=proposal,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        registered_report = self._post(REGISTERED_REPORT)
        self.service.attach_stage(journey, registered_report)

        # Act
        stages = self.service.stages(journey)

        # Assert
        self.assertEqual(
            [stage.stage for stage in stages],
            [
                JOURNAL_STAGE_GRANT,
                JOURNAL_STAGE_PROPOSAL,
                JOURNAL_STAGE_REGISTERED_REPORT,
            ],
        )
        self.assertEqual(
            [stage.item for stage in stages],
            [grant, proposal, registered_report],
        )

    def _journey(self):
        proposal = self._post(PREREGISTRATION)
        journey = ResearchJourney.objects.create(
            created_by=self.user,
            preregistration_post=proposal,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        return journey

    def _post(self, document_type):
        return create_post(
            created_by=self.user,
            document_type=document_type,
            title=f"{document_type} title",
        )

    def _grant(self):
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=GRANT,
        )
        return Grant.objects.create(
            created_by=self.user,
            unified_document=unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Research Grant",
            description="Funding for the proposal.",
        )
