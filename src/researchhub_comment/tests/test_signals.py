from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from notification.models import Notification
from purchase.related_models.fundraise_model import Fundraise
from purchase.related_models.rsc_exchange_rate_model import RscExchangeRate
from reputation.related_models.distribution import Distribution as DistributionModel
from researchhub_comment.constants.rh_comment_thread_types import (
    AUTHOR_UPDATE,
    GENERIC_COMMENT,
)
from researchhub_comment.models import RhCommentModel, RhCommentThreadModel
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.follow_model import Follow
from user.tests.helpers import create_random_default_user


class CreateAuthorUpdateNotificationSignalTests(TestCase):

    def setUp(self):
        self.author = create_random_default_user("author")
        self.follower1 = create_random_default_user("follower1")
        self.follower2 = create_random_default_user("follower2")
        self.non_follower = create_random_default_user("non_follower")

        # Create separate unified documents for each post type
        self.preregistration_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.discussion_unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION,
        )

        # Create a preregistration document
        self.preregistration = ResearchhubPost.objects.create(
            title="Test Preregistration",
            document_type=PREREGISTRATION,
            created_by=self.author,
            unified_document=self.preregistration_unified_doc,
        )

        # Create a discussion document for negative test cases
        self.discussion = ResearchhubPost.objects.create(
            title="Test Discussion",
            document_type=DISCUSSION,
            created_by=self.author,
            unified_document=self.discussion_unified_doc,
        )

        # Create follows for the preregistration
        Follow.objects.create(
            user=self.follower1,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.preregistration.id,
        )
        Follow.objects.create(
            user=self.follower2,
            content_type=ContentType.objects.get_for_model(ResearchhubPost),
            object_id=self.preregistration.id,
        )

    def test_creates_notifications_for_author_update_on_preregistration(self):
        """
        Test that notifications are created for followers when an author
        update is posted on a preregistration.
        """
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.preregistration,
            created_by=self.author,
        )

        # Act
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "This is an author update"},
            comment_type=AUTHOR_UPDATE,
        )

        # Assert
        notifications = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE,
            content_type=ContentType.objects.get_for_model(RhCommentModel),
            object_id=comment.id,
            action_user=self.author,
        )

        self.assertEqual(notifications.count(), 2)

        # Check that notifications were created for the correct recipients
        recipient_ids = set(notifications.values_list("recipient_id", flat=True))
        expected_recipient_ids = {self.follower1.id, self.follower2.id}
        self.assertEqual(recipient_ids, expected_recipient_ids)

        # Verify notification details
        for notification in notifications:
            self.assertEqual(
                notification.notification_type, Notification.PREREGISTRATION_UPDATE
            )
            self.assertEqual(notification.action_user, self.author)
            self.assertEqual(notification.item, comment)
            self.assertEqual(
                notification.unified_document,
                self.preregistration.unified_document,
            )

    def test_no_notifications_for_generic_comment_thread(self):
        """
        Test that no notifications are created for generic comment threads.
        """
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            thread_type=GENERIC_COMMENT,
            content_object=self.preregistration,
            created_by=self.author,
        )

        # Act
        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "This is a generic comment"},
            comment_type=GENERIC_COMMENT,
        )

        # Assert
        # Check that no author update notifications were created
        notifications = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE
        )
        self.assertEqual(notifications.count(), 0)

    def test_no_notifications_for_non_preregistration_document(self):
        """
        Test that no notifications are created for author updates on
        non-preregistration documents.
        """
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.discussion,
            created_by=self.author,
        )

        # Act
        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "Author update on discussion"},
            comment_type=AUTHOR_UPDATE,
        )

        # Assert
        # Check that no author update notifications were created
        notifications = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE
        )
        self.assertEqual(notifications.count(), 0)

    def test_no_notifications_when_no_followers(self):
        """
        Test that no notifications are created when there are no followers.
        """
        # Arrange
        unified_document = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        preregistration_no_followers = ResearchhubPost.objects.create(
            title="Test Preregistration No Followers",
            document_type=PREREGISTRATION,
            created_by=self.author,
            unified_document=unified_document,
        )

        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=preregistration_no_followers,
            created_by=self.author,
        )

        # Act
        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "This is an author update"},
            comment_type=AUTHOR_UPDATE,
        )

        # Assert
        notifications = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE
        )
        self.assertEqual(notifications.count(), 0)

    @patch("notification.models.Notification.send_notification")
    def test_send_notification_called_for_each_follower(self, mock_send_notification):
        """
        Test that send_notification is called for each notification created.
        """
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.preregistration,
            created_by=self.author,
        )

        # Act

        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "This is an author update"},
            comment_type=AUTHOR_UPDATE,
        )

        # Assert
        # Verify send_notification was called twice (once for each follower)
        self.assertEqual(mock_send_notification.call_count, 2)

    def test_signal_handles_update_operations(self):
        """
        Test that the signal only processes newly created comments,
        not updates.
        """
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.preregistration,
            created_by=self.author,
        )

        # Create author update comment
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "This is an author update"},
            comment_type=AUTHOR_UPDATE,
        )

        # Clear notifications from creation
        Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE
        ).delete()

        # Act
        # Update the comment (this should not trigger the signal)
        comment.comment_content_json = {"text": "Updated author update"}
        comment.save()

        # Assert
        # Check that no new notifications were created on update
        notifications = Notification.objects.filter(
            notification_type=Notification.PREREGISTRATION_UPDATE
        )
        self.assertEqual(notifications.count(), 0)


class RewardPreregistrationUpdateSignalTests(TestCase):

    def setUp(self):
        self.author = create_random_default_user("reward_author")
        self.unified_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=PREREGISTRATION,
        )
        self.preregistration = ResearchhubPost.objects.create(
            title="Test Preregistration",
            document_type=PREREGISTRATION,
            created_by=self.author,
            unified_document=self.unified_doc,
        )
        RscExchangeRate.objects.create(
            rate=0.5, real_rate=0.5,
            price_source="COIN_GECKO", target_currency="USD",
        )
        self.reward_qs = DistributionModel.objects.filter(
            recipient=self.author,
            distribution_type="PREREGISTRATION_UPDATE_REWARD",
        )

    def _create_fundraise(self, status=Fundraise.COMPLETED):
        return Fundraise.objects.create(
            created_by=self.author,
            unified_document=self.unified_doc,
            goal_amount=Decimal("100.00"),
            goal_currency="USD",
            status=status,
        )

    def _create_reminder(self, fundraise):
        return Notification.objects.create(
            item=fundraise,
            action_user=self.author,
            recipient=self.author,
            unified_document=self.unified_doc,
            notification_type=Notification.PREREGISTRATION_UPDATE_REMINDER,
        )

    def _post_author_update(self):
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=self.preregistration,
            created_by=self.author,
        )
        return RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "Monthly progress update"},
            comment_type=AUTHOR_UPDATE,
        )

    def test_rewards_author_for_completed_fundraise(self):
        # Arrange
        fundraise = self._create_fundraise()
        self._create_reminder(fundraise)
        # Act
        self._post_author_update()
        # Assert
        self.assertEqual(self.reward_qs.count(), 1)
        expected_rsc = RscExchangeRate.usd_to_rsc(50)
        self.assertAlmostEqual(float(self.reward_qs.first().amount), expected_rsc, places=2)

    def test_skips_without_reminder(self):
        # Arrange
        self._create_fundraise()
        # Act
        self._post_author_update()
        # Assert
        self.assertEqual(self.reward_qs.count(), 0)

    def test_skips_open_and_closed(self):
        # Arrange
        f_open = self._create_fundraise(status=Fundraise.OPEN)
        f_closed = self._create_fundraise(status=Fundraise.CLOSED)
        self._create_reminder(f_open)
        self._create_reminder(f_closed)
        # Act
        self._post_author_update()
        # Assert
        self.assertEqual(self.reward_qs.count(), 0)

    def test_deduplicates_within_same_month(self):
        # Arrange
        fundraise = self._create_fundraise()
        self._create_reminder(fundraise)
        # Act
        self._post_author_update()
        self._post_author_update()
        # Assert
        self.assertEqual(self.reward_qs.count(), 1)

    def test_skips_non_preregistration(self):
        # Arrange
        discussion_doc = ResearchhubUnifiedDocument.objects.create(
            document_type=DISCUSSION,
        )
        discussion = ResearchhubPost.objects.create(
            title="Test Discussion",
            document_type=DISCUSSION,
            created_by=self.author,
            unified_document=discussion_doc,
        )
        fundraise = self._create_fundraise()
        self._create_reminder(fundraise)
        # Act
        thread = RhCommentThreadModel.objects.create(
            thread_type=AUTHOR_UPDATE,
            content_object=discussion,
            created_by=self.author,
        )
        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.author,
            comment_content_json={"text": "Update"},
            comment_type=AUTHOR_UPDATE,
        )
        # Assert
        self.assertEqual(self.reward_qs.count(), 0)
