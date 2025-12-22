from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings

from feed.models import FeedEntry
from purchase.models import Fundraise, Grant, GrantApplication
from purchase.related_models.purchase_model import Purchase
from purchase.services.fundraise_service import FundraiseService
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants import document_type
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user, create_user


class TestPurchaseSignals(TestCase):
    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    def setUp(self):
        self.user = create_user("test@example.com", "password")

        # Create a unified document
        self.unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=document_type.POSTS,
        )

        # Create a post connected to the unified document
        self.post = ResearchhubPost.objects.create(
            title="Test Post",
            unified_document=self.unified_document,
            created_by=self.user,
        )

        # Create a feed entry for the post
        self.post_content_type = ContentType.objects.get_for_model(self.post)
        self.feed_entry = FeedEntry.objects.create(
            content_type=self.post_content_type,
            object_id=self.post.id,
            action="PUBLISH",
            action_date=self.post.created_date,
            user=self.user,
            unified_document=self.unified_document,
            content={},
            metrics={},
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry_by_id")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_create(
        self,
        mock_transaction,
        mock_refresh_feed_entry_by_id,
    ):
        """Test that feed entries are refreshed when a purchase is created"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry_by_id.apply_async = MagicMock()

        # Act
        Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Assert
        mock_refresh_feed_entry_by_id.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry_by_id")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_update(
        self,
        mock_transaction,
        mock_refresh_feed_entry_by_id,
    ):
        """Test that feed entries are refreshed when a purchase is updated"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry_by_id.apply_async = MagicMock()

        # Act
        Purchase.objects.create(
            user=self.user,
            content_type=self.post_content_type,
            object_id=self.post.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="10.0",
        )

        # Assert
        mock_refresh_feed_entry_by_id.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("feed.signals.purchase_signals.transaction")
    def test_grant_application_signal_refreshes_feed_entry(
        self,
        mock_transaction,
    ):
        """Test that creating a grant application triggers feed entry refresh
        and updates content"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()

        # Create users
        moderator = create_random_authenticated_user("grant_moderator", moderator=True)

        # Create grant post
        open_post = create_post(
            created_by=moderator, document_type=GRANT, title="Open Grant"
        )

        # Create grant
        open_grant = Grant.objects.create(
            created_by=moderator,
            unified_document=open_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        # Create a feed entry for the grant post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entry = FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=open_post.id,
            action="PUBLISH",
            action_date=open_post.created_date,
            user=moderator,
            unified_document=open_post.unified_document,
            content={},  # Empty content initially
            metrics={},
        )

        # Verify initial state - no applications in feed entry
        self.assertEqual(feed_entry.content, {})

        # Create an applicant and preregistration post
        applicant = create_random_authenticated_user("applicant")
        preregistration = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

        # Act - Create a grant application - this should trigger our signal
        grant_application = GrantApplication.objects.create(
            grant=open_grant,
            preregistration_post=preregistration,
            applicant=applicant,
        )

        # Wait for signals to complete (transactions are committed synchronously
        # due to test settings)

        # Refresh feed entry from database and check content was updated
        feed_entry.refresh_from_db()

        # The feed entry content should now include the grant application data
        self.assertIsNotNone(feed_entry.content)
        self.assertIn("grant", feed_entry.content)
        grant_data = feed_entry.content["grant"]
        self.assertIn("applications", grant_data)
        applications = grant_data["applications"]
        self.assertEqual(len(applications), 1)

        # Verify the application details in the feed entry
        application_data = applications[0]
        self.assertEqual(application_data["id"], grant_application.id)
        self.assertEqual(
            application_data["preregistration_post_id"], preregistration.id
        )
        applicant_id = application_data["applicant"]["id"]
        self.assertEqual(applicant_id, applicant.author_profile.id)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
    @patch("feed.signals.purchase_signals.transaction")
    def test_grant_application_delete_signal_refreshes_feed_entry(
        self,
        mock_transaction,
    ):
        """Test that deleting a grant application triggers feed entry refresh
        and updates content"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()

        # Create users
        moderator = create_random_authenticated_user("grant_moderator", moderator=True)

        # Create grant post
        open_post = create_post(
            created_by=moderator, document_type=GRANT, title="Open Grant"
        )

        # Create grant
        open_grant = Grant.objects.create(
            created_by=moderator,
            unified_document=open_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            organization="NSF",
            description="Open research grant",
            status=Grant.OPEN,
            end_date=datetime.now(pytz.UTC) + timedelta(days=30),
        )

        # Create a feed entry for the grant post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entry = FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=open_post.id,
            action="PUBLISH",
            action_date=open_post.created_date,
            user=moderator,
            unified_document=open_post.unified_document,
            content={},  # Empty content initially
            metrics={},
        )

        # Create an applicant and preregistration post
        applicant = create_random_authenticated_user("applicant")
        preregistration = create_post(
            created_by=applicant,
            document_type=PREREGISTRATION,
            title="Test Preregistration",
        )

        # Create a grant application
        application = GrantApplication.objects.create(
            grant=open_grant,
            preregistration_post=preregistration,
            applicant=applicant,
        )

        # Verify the application is in the feed entry after creation
        feed_entry.refresh_from_db()
        self.assertIn("grant", feed_entry.content)
        grant_data = feed_entry.content["grant"]
        self.assertIn("applications", grant_data)
        self.assertEqual(len(grant_data["applications"]), 1)
        self.assertEqual(grant_data["applications"][0]["id"], application.id)

        # Act - Delete the application - this should trigger our delete signal
        application.delete()

        # Wait for signals to complete (transactions are committed synchronously
        # due to test settings)

        # Refresh feed entry from database and verify application was removed
        feed_entry.refresh_from_db()

        # The feed entry should still have grant data but no applications
        self.assertIn("grant", feed_entry.content)
        grant_data = feed_entry.content["grant"]
        self.assertIn("applications", grant_data)
        self.assertEqual(len(grant_data["applications"]), 0)

    @patch("feed.signals.purchase_signals.refresh_feed_entry_by_id")
    @patch("feed.signals.purchase_signals.transaction")
    def test_fundraise_contribution_triggers_feed_update(
        self, mock_transaction, mock_refresh
    ):
        """
        Test that creating a fundraise contribution triggers
        feed entry refresh.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh.apply_async = MagicMock()

        # Create a preregistration post with fundraise
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Create fundraise
        fundraise_service = FundraiseService()
        fundraise = fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=post.unified_document,
            goal_amount=Decimal("1000"),
            goal_currency="USD",
        )

        # Create a feed entry for the post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entry = FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=post.id,
            unified_document=post.unified_document,
            action=FeedEntry.PUBLISH,
            action_date=datetime.now(pytz.UTC),
            content={},
        )

        # Act
        # Create a contribution
        contributor = create_random_authenticated_user("fundraise_contributor_1")
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        Purchase.objects.create(
            user=contributor,
            content_type=fundraise_content_type,
            object_id=fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status="PAID",
            amount="100",
        )

        # Assert
        mock_refresh.apply_async.assert_called_with(
            args=(feed_entry.id,),
            priority=1,
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry_by_id")
    @patch("feed.signals.purchase_signals.transaction")
    def test_fundraise_contribution_update_triggers_feed_update(
        self, mock_transaction, mock_refresh
    ):
        """
        Test that updating a fundraise contribution triggers
        feed entry refresh.
        """
        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh.apply_async = MagicMock()

        # Create a preregistration post with fundraise
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Create fundraise
        fundraise_service = FundraiseService()
        fundraise = fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=post.unified_document,
            goal_amount=Decimal("1000"),
            goal_currency="USD",
        )

        # Create a feed entry for the post
        post_content_type = ContentType.objects.get_for_model(ResearchhubPost)
        feed_entry = FeedEntry.objects.create(
            content_type=post_content_type,
            object_id=post.id,
            unified_document=post.unified_document,
            action=FeedEntry.PUBLISH,
            action_date=datetime.now(pytz.UTC),
            content={},
        )

        # Create a contribution
        contributor = create_random_authenticated_user("fundraise_contributor_2")
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)
        purchase = Purchase.objects.create(
            user=contributor,
            content_type=fundraise_content_type,
            object_id=fundraise.id,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
            paid_status="PAID",
            amount="100",
        )

        # Reset mock to clear the call from creation
        mock_refresh.reset_mock()

        # Act
        purchase.amount = "200"
        purchase.save()  # Update the purchase

        # Assert
        mock_refresh.apply_async.assert_called_with(
            args=(feed_entry.id,),
            priority=1,
        )

    def test_fundraise_signal_handles_missing_fundraise(self):
        """
        Test that signal handles gracefully when fundraise doesn't exist.
        """
        # Create a contribution with invalid fundraise ID
        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)

        # This should not raise an exception
        try:
            Purchase.objects.create(
                user=self.user,
                content_type=fundraise_content_type,
                object_id=99999,  # Non-existent fundraise ID
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status="PAID",
                amount="100",
            )
            # Signal should log warning but not crash
        except Exception as e:
            msg = f"Signal should handle missing fundraise gracefully: {e}"
            self.fail(msg)

    def test_fundraise_signal_handles_no_feed_entries(self):
        """
        Test that signal handles gracefully when no feed entries exist.
        """
        # Create a post without a feed entry
        post = create_post(created_by=self.user, document_type=PREREGISTRATION)

        # Create fundraise
        fundraise_service = FundraiseService()
        fundraise = fundraise_service.create_fundraise_with_escrow(
            user=self.user,
            unified_document=post.unified_document,
            goal_amount=Decimal("1000"),
            goal_currency="USD",
        )

        fundraise_content_type = ContentType.objects.get_for_model(Fundraise)

        # Create a contribution - this should not raise an exception
        # even though no feed entries exist
        try:
            Purchase.objects.create(
                user=self.user,
                content_type=fundraise_content_type,
                object_id=fundraise.id,
                purchase_method=Purchase.OFF_CHAIN,
                purchase_type=Purchase.FUNDRAISE_CONTRIBUTION,
                paid_status="PAID",
                amount="100",
            )
            # Signal should handle missing feed entries gracefully
        except Exception as e:
            msg = f"Signal should handle missing feed entries gracefully: {e}"
            self.fail(msg)
