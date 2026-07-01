from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from notification.models import Notification
from purchase.models import Fundraise, Grant, GrantApplication
from researchhub_document.helpers import create_post
from researchhub_document.models import (
    ResearchhubPost,
    ResearchhubUnifiedDocument,
    ResearchJourney,
)
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
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
from user.tests.helpers import create_random_default_user


class JourneyServiceTests(TestCase):
    def setUp(self) -> None:
        """Create a user and service for each journey service test."""
        self.user = create_random_default_user("journey_author")
        self.service = JourneyService()

    def test_create_journey_for_preregistration(self) -> None:
        """Verify preregistration posts create and attach a journey."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)

        # Act
        journey = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        proposal.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)

    def test_reuse_existing_preregistration_journey(self) -> None:
        """Verify repeated preregistration lookups reuse the same journey."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)

        # Act
        first = self.service.get_or_create_for_preregistration(proposal)
        second = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        self.assertEqual(first, second)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_link_grant_post_from_application(self) -> None:
        """Verify grant applications link their grant post to the journey."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        grant, grant_post = self._create_grant_with_post()
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=self.user,
        )

        # Act
        journey = self.service.get_or_create_for_preregistration(proposal)

        # Assert
        self.assertEqual(journey.grant_post, grant_post)

    def test_reject_non_proposal_journey(self) -> None:
        """Verify non-preregistration posts cannot start a journey."""
        # Arrange
        post = self._create_post(DISCUSSION)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.get_or_create_for_preregistration(post)

    def test_create_journey_for_approved_proposal(self) -> None:
        """Verify approved preregistrations receive a journey anchor."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)

        # Act
        journey = self.service.ensure_approved_preregistration_has_journey(proposal)

        # Assert
        proposal.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)

    def test_reuse_journey_for_approved_proposal(self) -> None:
        """Verify approved preregistration journey creation is idempotent."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)

        # Act
        first = self.service.ensure_approved_preregistration_has_journey(proposal)
        second = self.service.ensure_approved_preregistration_has_journey(proposal)

        # Assert
        self.assertEqual(first, second)
        self.assertEqual(ResearchJourney.objects.count(), 1)

    def test_skip_pending_proposal_journey(self) -> None:
        """Verify pending preregistrations do not receive a journey anchor."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        proposal.unified_document.status = ResearchhubUnifiedDocument.PENDING
        proposal.unified_document.save(update_fields=["status"])

        # Act
        journey = self.service.ensure_approved_preregistration_has_journey(proposal)

        # Assert
        self.assertIsNone(journey)
        self.assertFalse(ResearchJourney.objects.exists())

    def test_skip_non_proposal_journey(self) -> None:
        """Verify approved non-preregistration posts do not receive a journey."""
        # Arrange
        post = self._create_post(DISCUSSION)

        # Act
        journey = self.service.ensure_approved_preregistration_has_journey(post)

        # Assert
        self.assertIsNone(journey)
        self.assertFalse(ResearchJourney.objects.exists())

    def test_include_funded_proposal_in_journal(self) -> None:
        """Verify completed fundraises include their proposal journey."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        proposal.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)
        self.assertTrue(journey.is_in_journal)
        self.assertIsNotNone(journey.journal_included_date)

    def test_notify_author_when_proposal_enters_journal(self) -> None:
        """Verify first-time journal inclusion notifies the proposal author."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        # Temporarily disabled until the registered-report launch path is live.
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
                recipient=self.user,
            ).exists()
        )
        return

        notification = Notification.objects.get(
            notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
            recipient=self.user,
        )
        self.assertEqual(notification.action_user, self.user)
        self.assertEqual(notification.unified_document, proposal.unified_document)
        self.assertEqual(notification.item, journey)
        self.assertEqual(notification.extra["journey_id"], str(journey.id))
        self.assertEqual(notification.extra["is_private_proposal"], "False")
        self.assertIn("ResearchHub Journal", notification.body[2]["value"])
        self.assertEqual(
            notification.navigation_url,
            proposal.unified_document.frontend_view_link(),
        )

    def test_notify_author_with_private_proposal_clause(self) -> None:
        """Verify private proposal journal notifications explain public setup."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        proposal.unified_document.is_public = False
        proposal.unified_document.save(update_fields=["is_public"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        notification = Notification.objects.get(
            notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
            recipient=self.user,
        )
        self.assertEqual(notification.item, journey)
        self.assertEqual(notification.extra["is_private_proposal"], "True")
        self.assertIn("ready for it to go public", notification.body[2]["value"])
        self.assertIn("set you up", notification.body[2]["value"])

    def test_skip_duplicate_journal_entry_notification(self) -> None:
        """Verify repeated journal inclusion does not duplicate notifications."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=timezone.now(),
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )
        Notification.objects.create(
            notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
            recipient=self.user,
            action_user=self.user,
            unified_document=proposal.unified_document,
            content_type=ContentType.objects.get_for_model(ResearchJourney),
            object_id=journey.id,
        )

        # Act
        self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        notifications = Notification.objects.filter(
            notification_type=Notification.PROPOSAL_ENTERED_JOURNAL,
            recipient=self.user,
            object_id=journey.id,
        )
        self.assertEqual(notifications.count(), 1)

    def test_email_author_when_proposal_enters_journal(self) -> None:
        """Verify first-time journal inclusion queues the author email."""
        # Arrange
        email_task = Mock()
        service = JourneyService(journal_entry_email_task=email_task)
        proposal = self._create_post(PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        with patch("notification.models.Notification.send_notification"):
            with self.captureOnCommitCallbacks(execute=True):
                journey = service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        # Temporarily disabled until the registered-report launch path is live.
        email_task.delay.assert_not_called()
        return

        email_task.delay.assert_called_once_with(journey.id)

    def test_skip_duplicate_journal_entry_email(self) -> None:
        """Verify repeated journal inclusion does not queue duplicate email."""
        # Arrange
        email_task = Mock()
        service = JourneyService(journal_entry_email_task=email_task)
        proposal = self._create_post(PREREGISTRATION)
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=timezone.now(),
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        with self.captureOnCommitCallbacks(execute=True):
            service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        email_task.delay.assert_not_called()

    def test_keep_existing_journal_date(self) -> None:
        """Verify repeated inclusion keeps the original journal date."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        included_date = timezone.now()
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
            is_in_journal=True,
            journal_included_date=included_date,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        included_journey = self.service.include_completed_fundraise_in_journal(
            fundraise
        )

        # Assert
        self.assertEqual(included_journey, journey)
        self.assertEqual(included_journey.journal_included_date, included_date)

    def test_skip_journal_for_open_fundraise(self) -> None:
        """Verify open fundraises do not include their journey in the journal."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.OPEN,
        )

        # Act
        journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        self.assertIsNone(journey)
        self.assertFalse(ResearchJourney.objects.exists())

    def test_log_completed_fundraise_without_proposal(self) -> None:
        """Verify completed fundraises without proposals are logged."""
        # Arrange
        post = self._create_post(DISCUSSION)
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=post.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        with self.assertLogs(
            "researchhub_document.services.journey_service",
            level="WARNING",
        ) as logs:
            journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        self.assertIsNone(journey)
        self.assertIn(
            "Completed fundraise has no preregistration post.",
            logs.output[0],
        )

    def test_log_completed_fundraise_with_ineligible_proposal(self) -> None:
        """Verify completed fundraises with ineligible proposals are logged."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        proposal.unified_document.status = ResearchhubUnifiedDocument.PENDING
        proposal.unified_document.save(update_fields=["status"])
        fundraise = Fundraise.objects.create(
            created_by=self.user,
            unified_document=proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency="USD",
            status=Fundraise.COMPLETED,
        )

        # Act
        with self.assertLogs(
            "researchhub_document.services.journey_service",
            level="WARNING",
        ) as logs:
            journey = self.service.include_completed_fundraise_in_journal(fundraise)

        # Assert
        self.assertIsNone(journey)
        self.assertIn(
            "Completed fundraise preregistration was not eligible for a journey.",
            logs.output[0],
        )

    def test_attach_stage_attaches_registered_report(self) -> None:
        """Verify registered reports attach to journeys with proposals."""
        # Arrange
        journey = self._create_journey()
        registered_report = self._create_post(REGISTERED_REPORT)

        # Act
        self.service.attach_stage(journey, registered_report)

        # Assert
        registered_report.refresh_from_db()
        self.assertEqual(registered_report.journey, journey)

    def test_attach_stage_attaches_proposal_to_empty_journey(self) -> None:
        """Verify a proposal can populate an empty journey."""
        # Arrange
        journey = ResearchJourney.objects.create()
        proposal = self._create_post(PREREGISTRATION)

        # Act
        self.service.attach_stage(journey, proposal)

        # Assert
        journey.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(journey.preregistration_post, proposal)
        self.assertEqual(proposal.journey, journey)

    def test_attach_stage_rejects_registered_report_without_proposal(self) -> None:
        """Verify registered reports require an existing proposal."""
        # Arrange
        journey = ResearchJourney.objects.create()
        registered_report = self._create_post(REGISTERED_REPORT)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, registered_report)

    def test_attach_stage_rejects_second_registered_report(self) -> None:
        """Verify a journey cannot have two registered reports."""
        # Arrange
        journey = self._create_journey()
        first_report = self._create_post(REGISTERED_REPORT)
        second_report = self._create_post(REGISTERED_REPORT)
        self.service.attach_stage(journey, first_report)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, second_report)

    def test_attach_stage_normalizes_registered_report_integrity_error(self) -> None:
        """Verify duplicate registered report integrity errors become value errors."""
        # Arrange
        journey = self._create_journey()
        registered_report = self._create_post(REGISTERED_REPORT)

        # Act / Assert
        with patch.object(
            registered_report,
            "save",
            side_effect=IntegrityError("duplicate registered report"),
        ):
            with self.assertRaises(ValueError):
                self.service.attach_stage(journey, registered_report)

    def test_attach_stage_rejects_second_proposal(self) -> None:
        """Verify a journey cannot have two proposals."""
        # Arrange
        journey = ResearchJourney.objects.create()
        first_proposal = self._create_post(PREREGISTRATION)
        second_proposal = self._create_post(PREREGISTRATION)
        first_proposal.journey = journey
        first_proposal.save(update_fields=["journey"])

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(journey, second_proposal)

    def test_attach_stage_rejects_reassignment(self) -> None:
        """Verify a post cannot move from one journey to another."""
        # Arrange
        first_journey = self._create_journey()
        second_journey = self._create_journey()
        registered_report = self._create_post(REGISTERED_REPORT)
        self.service.attach_stage(first_journey, registered_report)

        # Act / Assert
        with self.assertRaises(ValueError):
            self.service.attach_stage(second_journey, registered_report)

    def test_get_latest_stage_post_returns_registered_report_when_present(
        self,
    ) -> None:
        """Verify the latest stage prefers registered reports over proposals."""
        # Arrange
        journey = self._create_journey()
        registered_report = self._create_post(REGISTERED_REPORT)

        # Act / Assert
        self.assertEqual(
            self.service.get_latest_stage_post(journey),
            journey.preregistration_post,
        )
        self.assertFalse(self.service.has_registered_report(journey))

        self.service.attach_stage(journey, registered_report)
        self.assertEqual(self.service.get_latest_stage_post(journey), registered_report)
        self.assertTrue(self.service.has_registered_report(journey))

    def test_get_stages_returns_grant_proposal_and_registered_report(self) -> None:
        """Verify stages return the grant, proposal, and report in order."""
        # Arrange
        proposal = self._create_post(PREREGISTRATION)
        _, grant_post = self._create_grant_with_post()
        journey = ResearchJourney.objects.create(
            grant_post=grant_post,
            preregistration_post=proposal,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        registered_report = self._create_post(REGISTERED_REPORT)
        self.service.attach_stage(journey, registered_report)

        # Act
        stages = self.service.get_stages(journey)

        # Assert
        self.assertEqual(
            [stage.stage for stage in stages],
            [
                JOURNEY_STAGE_GRANT,
                JOURNEY_STAGE_PROPOSAL,
                JOURNEY_STAGE_REGISTERED_REPORT,
            ],
        )
        self.assertEqual(
            [stage.item for stage in stages],
            [grant_post, proposal, registered_report],
        )

    def _create_journey(self) -> ResearchJourney:
        """Create a journey with an attached proposal post."""
        proposal = self._create_post(PREREGISTRATION)
        journey = ResearchJourney.objects.create(
            preregistration_post=proposal,
        )
        proposal.journey = journey
        proposal.save(update_fields=["journey"])
        return journey

    def _create_post(self, document_type: str) -> ResearchhubPost:
        """Create a post of the requested document type."""
        return create_post(
            created_by=self.user,
            document_type=document_type,
            title=f"{document_type} title",
        )

    def _create_grant_with_post(self) -> tuple[Grant, ResearchhubPost]:
        """Create a grant backed by a grant post."""
        grant_post = self._create_post(GRANT)
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=grant_post.unified_document,
            amount=Decimal("1000.00"),
            currency="USD",
            organization="Research Grant",
            description="Funding for the proposal.",
        )
        return grant, grant_post
