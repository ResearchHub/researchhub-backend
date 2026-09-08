from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.test import TestCase

from mailing_list.services import EmailService
from notification.models import Notification
from purchase.models import Grant, GrantApplication
from purchase.tasks import send_grant_application_email
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from user.tests.helpers import create_random_default_user
from utils.test_helpers import AWSMockTransactionTestCase


class GrantApplicationNotificationSignalTests(TestCase):
    def setUp(self):
        # Arrange
        self.owner = create_random_default_user("grant_owner")
        self.applicant = create_random_default_user("applicant")
        self.grant_post = create_post(created_by=self.owner, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Test grant",
            status=Grant.OPEN,
        )
        self.proposal = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Test Proposal",
        )

    def test_creates_notification_for_grant_owner(self):
        # Act
        application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.proposal,
            applicant=self.applicant,
        )

        # Assert
        notification = Notification.objects.get(
            notification_type=Notification.GRANT_APPLICATION_SUBMITTED,
            recipient=self.owner,
        )
        self.assertEqual(notification.action_user, self.applicant)
        self.assertEqual(notification.object_id, application.id)
        self.assertEqual(
            notification.unified_document_id, self.proposal.unified_document_id
        )
        self.assertEqual(
            notification.content_type,
            ContentType.objects.get_for_model(GrantApplication),
        )

    def test_no_notification_on_get_or_create_when_not_created(self):
        # Arrange
        GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.proposal,
            applicant=self.applicant,
        )
        Notification.objects.all().delete()

        # Act
        _, created = GrantApplication.objects.get_or_create(
            grant=self.grant,
            preregistration_post=self.proposal,
            defaults={"applicant": self.applicant},
        )

        # Assert
        self.assertFalse(created)
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.GRANT_APPLICATION_SUBMITTED
            ).exists()
        )


class GrantApplicationNotificationDispatchTests(AWSMockTransactionTestCase):
    def setUp(self) -> None:
        """Create a funding opportunity and an applicant's proposal."""
        super().setUp()

        # Arrange
        self.owner = create_random_default_user("grant_owner_tx")
        self.applicant = create_random_default_user("applicant_tx")
        self.grant_post = create_post(created_by=self.owner, document_type=GRANT)
        self.grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=self.grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Test grant",
            status=Grant.OPEN,
        )
        self.proposal = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Test Proposal TX",
        )

    @patch.object(EmailService, "send_email")
    @patch.object(
        send_grant_application_email, "delay", new=send_grant_application_email
    )
    @patch.object(Notification, "send_notification")
    def test_dispatches_notifications_after_commit(
        self,
        mock_send_notification: MagicMock,
        mock_send_email: MagicMock,
    ) -> None:
        """Send in-app and email notifications only after the application commits."""
        # Arrange
        proposal_url = self.proposal.unified_document.frontend_view_link()

        # Act
        with transaction.atomic():
            GrantApplication.objects.create(
                grant=self.grant,
                preregistration_post=self.proposal,
                applicant=self.applicant,
            )
            mock_send_notification.assert_not_called()
            mock_send_email.assert_not_called()

        # Assert
        mock_send_notification.assert_called_once()
        mock_send_email.assert_called_once()
        email = mock_send_email.call_args.kwargs
        self.assertEqual(email["recipients"], self.owner.email)
        self.assertEqual(
            email["email_context"]["action"]["frontend_view_link"], proposal_url
        )
