from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

import pytz
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from feed.models import FeedEntry
from feed.serializers import PostSerializer
from feed.views.base_feed_view import BaseFeedView
from purchase.models import Grant, GrantApplication
from purchase.related_models.purchase_model import Purchase
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

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_create(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that feed entries are refreshed when a purchase is created"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

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
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_refresh_feed_entries_on_purchase_update(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that feed entries are refreshed when a purchase is updated"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

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
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(self.feed_entry.id,),
                    priority=1,
                ),
            ]
        )

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_grant_application_signal_refreshes_feed_entry(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that creating a grant application triggers feed entry refresh"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

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

        # Act - Create a grant application - this should trigger our signal
        grant_application = GrantApplication.objects.create(
            grant=open_grant,
            preregistration_post=preregistration,
            applicant=applicant,
        )

        # Assert - The signal should have triggered feed entry refresh
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(feed_entry.id,),
                    priority=1,
                ),
            ]
        )

        # Additional check: Verify that serializing the post now includes
        # grant applications
        context = BaseFeedView().get_common_serializer_context()
        serializer = PostSerializer(open_post, context=context)
        data = serializer.data

        # Check that grant data includes applications
        self.assertIsNotNone(data["grant"])
        grant_data = data["grant"]
        self.assertIn("applications", grant_data)
        applications = grant_data["applications"]
        self.assertEqual(len(applications), 1)

        # Verify the application details
        application_data = applications[0]
        self.assertEqual(application_data["id"], grant_application.id)
        self.assertEqual(
            application_data["preregistration_post_id"], preregistration.id
        )
        applicant_id = application_data["applicant"]["id"]
        self.assertEqual(applicant_id, applicant.author_profile.id)

    @patch("feed.signals.purchase_signals.refresh_feed_entry")
    @patch("feed.signals.purchase_signals.transaction")
    def test_grant_application_delete_signal_refreshes_feed_entry(
        self,
        mock_transaction,
        mock_refresh_feed_entry,
    ):
        """Test that deleting a grant application triggers feed entry refresh"""

        # Arrange
        mock_transaction.on_commit = lambda func: func()
        mock_refresh_feed_entry.apply_async = MagicMock()

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

        # Reset the mock to ignore the create signal call
        mock_refresh_feed_entry.apply_async.reset_mock()

        # Act - Delete the application - this should trigger our delete signal
        application.delete()

        # Assert - The delete signal should have triggered feed entry refresh
        mock_refresh_feed_entry.apply_async.assert_has_calls(
            [
                call(
                    args=(feed_entry.id,),
                    priority=1,
                ),
            ]
        )
