from decimal import Decimal
from unittest.mock import AsyncMock, Mock

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from mailing_list.services import EmailService
from notification.models import Notification
from notification.services import NotificationService
from organizations.models import NonprofitFundraiseLink, NonprofitOrg
from purchase.endaoment import EndaomentService
from purchase.models import (
    Balance,
    FundingPool,
    Grant,
    GrantApplication,
    RscExchangeRate,
)
from purchase.related_models.constants.currency import USD
from purchase.services.funding_pool_service import FundingPoolService
from purchase.services.fundraise_notification_service import (
    FundraiseNotificationService,
)
from purchase.services.fundraise_service import FundraiseService
from reputation.models import BountyFee
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT as GRANT_DOC,
)
from researchhub_document.related_models.constants.document_type import PREREGISTRATION
from user.tests.helpers import create_random_default_user, create_user
from utils.test_helpers import AWSMockTransactionTestCase


class FundraiseNotificationServiceTests(AWSMockTransactionTestCase):
    """Verify author alerts follow committed contributions and distributions."""

    def setUp(self) -> None:
        """Create a proposal and inject mocked external delivery services."""
        super().setUp()
        self.creator = create_random_default_user("proposal_creator")
        self.contributor = create_random_default_user("proposal_contributor")
        self.proposal = create_post(
            created_by=self.creator, document_type=PREREGISTRATION
        )
        self.email_service = Mock(spec=EmailService)
        self.channel_layer = Mock(group_send=AsyncMock())
        self.endaoment_service = Mock(spec=EndaomentService)
        self.notification_service = FundraiseNotificationService(
            notification_service=NotificationService(channel_layer=self.channel_layer),
            email_service=self.email_service,
        )
        self.fundraise_service = FundraiseService(
            endaoment_service=self.endaoment_service,
            fundraise_notification_service=self.notification_service,
        )
        self.fundraise = self.fundraise_service.create_fundraise_with_escrow(
            user=self.creator,
            unified_document=self.proposal.unified_document,
            goal_amount=Decimal("1000.00"),
            goal_currency=USD,
        )
        RscExchangeRate.objects.create(rate=0.5, real_rate=0.5, target_currency=USD)
        self.notifications = Notification.objects.filter(
            notification_type=Notification.FUNDRAISE_CONTRIBUTION
        )

    def test_notify_authors_only_after_rsc_contribution_commits(self) -> None:
        """Notify each author once after commit and discard rolled-back alerts."""
        # Arrange
        create_user(email="bank@researchhub.com")
        create_user(email="revenue@researchhub.com")
        BountyFee.objects.create(rh_pct=Decimal("0.07"), dao_pct=Decimal("0.02"))
        self.proposal.authors.add(
            self.creator.author_profile, self.contributor.author_profile
        )
        Balance.objects.create(
            amount=200,
            user=self.contributor,
            content_type=ContentType.objects.get(model="distribution"),
            is_locked=True,
            lock_type=Balance.LockType.FUNDING_CREDIT,
        )

        # Act
        for rollback in (True, False):
            with self.subTest(rollback=rollback), transaction.atomic():
                purchase, error = self.fundraise_service.create_rsc_contribution(
                    self.contributor, self.fundraise, Decimal(100), use_credits=True
                )
                self.assertIsNone(error)
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())
                transaction.set_rollback(rollback)
            if rollback:
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())

        # Assert
        self.email_service.send_message_email.assert_called_once()
        self.assertCountEqual(
            self.email_service.send_message_email.call_args.args[0],
            [self.creator.email, self.contributor.email],
        )
        self.assertEqual(
            self.email_service.send_message_email.call_args.kwargs["link"],
            self.proposal.unified_document.frontend_view_link(),
        )
        self.assertCountEqual(
            self.notifications.values_list("recipient_id", "object_id"),
            [(self.creator.id, purchase.id), (self.contributor.id, purchase.id)],
        )
        self.assertEqual(self.channel_layer.group_send.await_count, 2)

    def test_notify_author_only_after_usd_contribution_commits(self) -> None:
        """Send submitted USD wording only after the contribution commits."""
        # Arrange
        nonprofit = NonprofitOrg.objects.create(
            name="Test Nonprofit", endaoment_org_id="endaoment_org_123"
        )
        NonprofitFundraiseLink.objects.create(
            fundraise=self.fundraise, nonprofit=nonprofit
        )
        self.endaoment_service.transfer_to_researchhub_fund.return_value = {
            "id": "transfer_123"
        }

        # Act
        for rollback in (True, False):
            with self.subTest(rollback=rollback), transaction.atomic():
                contribution, error = self.fundraise_service.create_usd_contribution(
                    user=self.contributor,
                    fundraise=self.fundraise,
                    amount_cents=10000,
                    origin_fund_id="fund_abc",
                )
                self.assertIsNone(error)
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())
                transaction.set_rollback(rollback)
            if rollback:
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())

        # Assert
        self.email_service.send_message_email.assert_called_once()
        self.assertEqual(
            self.email_service.send_message_email.call_args.args[0],
            [self.creator.email],
        )
        message = "submitted a contribution of 100.00 USD"
        self.assertIn(message, self.email_service.send_message_email.call_args.args[2])
        notification = self.notifications.get()
        self.assertEqual(notification.recipient, self.creator)
        self.assertEqual(notification.item, contribution)
        self.assertIn(message, "".join(part["value"] for part in notification.body))
        self.channel_layer.group_send.assert_awaited_once()

    def test_notify_author_only_after_pool_distribution_commits(self) -> None:
        """Notify the proposal author only after a pool distribution commits."""
        # Arrange
        grant_post = create_post(created_by=self.contributor, document_type=GRANT_DOC)
        grant = Grant.objects.create(
            created_by=self.contributor,
            unified_document=grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency=USD,
            organization="Test Org",
            description="Test grant",
            status=Grant.OPEN,
        )
        pool = FundingPool.objects.create(
            grant=grant, created_by=self.contributor, amount_holding=Decimal(200)
        )
        application = GrantApplication.objects.create(
            grant=grant, preregistration_post=self.proposal, applicant=self.creator
        )
        service = FundingPoolService(
            fundraise_notification_service=self.notification_service
        )

        # Act
        for rollback in (True, False):
            with self.subTest(rollback=rollback), transaction.atomic():
                distribution = service.distribute(
                    pool, self.contributor, Decimal(75), application.id
                )
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())
                transaction.set_rollback(rollback)
            if rollback:
                self.email_service.send_message_email.assert_not_called()
                self.channel_layer.group_send.assert_not_awaited()
                self.assertFalse(self.notifications.exists())

        # Assert
        self.email_service.send_message_email.assert_called_once()
        self.assertEqual(
            self.email_service.send_message_email.call_args.args[0],
            [self.creator.email],
        )
        notification = self.notifications.get()
        self.assertEqual(notification.recipient, self.creator)
        self.assertEqual(notification.item, distribution.fundraise_purchase)
        self.channel_layer.group_send.assert_awaited_once()
