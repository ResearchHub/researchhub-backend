from decimal import Decimal
from unittest.mock import MagicMock, patch

from discussion.models import Flag
from notification.models import Notification
from paper.tests.helpers import create_paper
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.related_models.verdict_model import Verdict
from user.services.content_moderation_service import ContentModerationService
from user.tests.helpers import create_random_authenticated_user
from utils.test_helpers import AWSMockTransactionTestCase


class ContentModerationServiceTests(AWSMockTransactionTestCase):
    def setUp(self):
        self.service = ContentModerationService()
        self.moderator = create_random_authenticated_user("cms_mod", moderator=True)
        self.author = create_random_authenticated_user("cms_author")
        self.post = self._pending_post()

    def _pending_post(self, document_type=DISCUSSION):
        post = create_post(created_by=self.author, document_type=document_type)
        unified_document = post.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return post

    def test_approve_marks_reviewed_and_notifies(self):
        # Arrange - self.post is a pending post created in setUp

        # Act
        self.service.approve_content(self.post, self.moderator)

        # Assert
        unified_document = self.post.unified_document
        unified_document.refresh_from_db()
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.APPROVED)
        self.assertEqual(unified_document.reviewed_by, self.moderator)
        self.assertIsNotNone(unified_document.reviewed_date)
        notification = Notification.objects.get(
            notification_type=Notification.CONTENT_APPROVED, recipient=self.author
        )
        self.assertTrue(notification.body)

    def test_decline_flags_removes_doc_and_notifies(self):
        # Arrange - self.post is a pending post created in setUp

        # Act
        self.service.decline_content(
            self.post, self.moderator, reason="Spam", reason_choice="SPAM"
        )

        # Assert
        unified_document = self.post.unified_document
        unified_document.refresh_from_db()
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.DECLINED)
        self.assertEqual(unified_document.reviewed_by, self.moderator)
        self.assertTrue(unified_document.is_removed)

        flag = Flag.objects.get(object_id=self.post.id)
        verdict = Verdict.objects.get(flag=flag)
        self.assertTrue(verdict.is_content_removed)
        self.assertEqual(flag.verdict_created_date, verdict.created_date)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.CONTENT_DECLINED,
                recipient=self.author,
            ).exists()
        )

    def test_approve_non_pending_content_raises(self):
        # Arrange
        self.post.unified_document.status = ResearchhubUnifiedDocument.APPROVED
        self.post.unified_document.save(update_fields=["status"])

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.approve_content(self.post, self.moderator)

    def test_decline_non_pending_content_raises(self):
        # Arrange
        self.post.unified_document.status = ResearchhubUnifiedDocument.DECLINED
        self.post.unified_document.save(update_fields=["status"])

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.decline_content(self.post, self.moderator)

    def test_approve_grant_delegates_to_grant_service(self):
        # Arrange
        grant, grant_post = self._grant_with_post()
        self.service._grant_service = MagicMock()

        # Act
        self.service.approve_content(grant_post, self.moderator)

        # Assert
        self.service._grant_service.approve_grant.assert_called_once_with(
            grant, self.moderator
        )

    def test_decline_grant_delegates_to_grant_service(self):
        # Arrange
        grant, grant_post = self._grant_with_post()
        self.service._grant_service = MagicMock()

        # Act
        self.service.decline_content(
            grant_post, self.moderator, reason="Spam", reason_choice="SPAM"
        )

        # Assert
        self.service._grant_service.decline_grant.assert_called_once_with(
            grant, self.moderator, "Spam", "SPAM"
        )

    def test_notification_failure_does_not_block_approve(self):
        # Arrange
        with patch(
            "user.services.content_moderation_service.Notification"
        ) as mock_notif_cls:
            mock_notif_cls.objects.create.side_effect = Exception("boom")
            mock_notif_cls.CONTENT_APPROVED = Notification.CONTENT_APPROVED

            # Act
            self.service.approve_content(self.post, self.moderator)

        # Assert
        unified_document = self.post.unified_document
        unified_document.refresh_from_db()
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.APPROVED)

    def _pending_paper(self):
        paper = create_paper(uploaded_by=self.author)
        unified_document = paper.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return paper

    def test_approve_paper_marks_reviewed_and_notifies(self):
        # Arrange
        paper = self._pending_paper()

        # Act
        self.service.approve_content(paper, self.moderator)

        # Assert
        unified_document = paper.unified_document
        unified_document.refresh_from_db()
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.APPROVED)
        self.assertEqual(unified_document.reviewed_by, self.moderator)
        self.assertIsNotNone(unified_document.reviewed_date)
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.CONTENT_APPROVED,
                recipient=self.author,
            ).exists()
        )

    def test_decline_paper_removes_and_flags(self):
        # Arrange
        paper = self._pending_paper()

        # Act
        self.service.decline_content(
            paper, self.moderator, reason="Spam", reason_choice="SPAM"
        )

        # Assert
        paper.refresh_from_db()
        unified_document = paper.unified_document
        unified_document.refresh_from_db()
        self.assertEqual(unified_document.status, ResearchhubUnifiedDocument.DECLINED)
        self.assertTrue(paper.is_removed)
        self.assertTrue(unified_document.is_removed)
        flag = Flag.objects.get(object_id=paper.id)
        self.assertTrue(Verdict.objects.filter(flag=flag).exists())
        self.assertTrue(
            Notification.objects.filter(
                notification_type=Notification.CONTENT_DECLINED,
                recipient=self.author,
            ).exists()
        )

    def _grant_with_post(self):
        grant_post = create_post(created_by=self.author, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.author,
            unified_document=grant_post.unified_document,
            amount=Decimal("50000.00"),
            currency="USD",
            description="Test grant",
        )
        return grant, grant_post
