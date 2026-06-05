from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase

from discussion.models import Flag
from notification.models import Notification
from paper.related_models.paper_model import Paper
from paper.tests.helpers import create_paper
from purchase.models import Grant
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    GRANT,
)
from researchhub_document.related_models.researchhub_post_model import ResearchhubPost
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.verdict_model import Verdict
from user.services.content_moderation_service import ContentModerationService
from user.tests.helpers import create_random_authenticated_user

EventType = RiskScoreEvent.EventType


class ContentModerationServiceTests(TestCase):
    def setUp(self):
        self.service = ContentModerationService()
        self.moderator = create_random_authenticated_user("cms_mod", moderator=True)
        self.author = create_random_authenticated_user("cms_author")
        self.post = self._pending_post()

    def _pending_post(self, document_type=DISCUSSION):
        post = create_post(created_by=self.author, document_type=document_type)
        post.status = ResearchhubPost.PENDING
        post.save(update_fields=["status"])
        return post

    def test_approve_marks_reviewed_and_notifies(self):
        # Act
        self.service.approve_content(self.post, self.moderator)

        # Assert
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, ResearchhubPost.APPROVED)
        self.assertEqual(self.post.reviewed_by, self.moderator)
        self.assertIsNotNone(self.post.reviewed_date)
        notification = Notification.objects.get(
            notification_type=Notification.CONTENT_APPROVED, recipient=self.author
        )
        self.assertTrue(notification.body)

    def test_decline_flags_removes_doc_and_notifies(self):
        # Act
        self.service.decline_content(
            self.post, self.moderator, reason="Spam", reason_choice="SPAM"
        )

        # Assert
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, ResearchhubPost.DECLINED)
        self.assertEqual(self.post.reviewed_by, self.moderator)
        self.assertTrue(self.post.unified_document.is_removed)

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

    def test_decline_scores_work_declined_not_censored(self):
        # Act
        with self.captureOnCommitCallbacks(execute=True):
            self.service.decline_content(
                self.post, self.moderator, reason="Spam", reason_choice="SPAM"
            )

        # Assert
        events = RiskScoreEvent.objects.filter(user=self.author)
        self.assertTrue(events.filter(event_type=EventType.WORK_DECLINED).exists())
        self.assertFalse(events.filter(event_type=EventType.CONTENT_CENSORED).exists())

    def test_approve_non_pending_content_raises(self):
        # Arrange
        self.post.status = ResearchhubPost.APPROVED
        self.post.save(update_fields=["status"])

        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.approve_content(self.post, self.moderator)

    def test_decline_non_pending_content_raises(self):
        # Arrange
        self.post.status = ResearchhubPost.DECLINED
        self.post.save(update_fields=["status"])

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
        with patch("user.services.moderation.Notification") as mock_notif_cls:
            mock_notif_cls.objects.create.side_effect = Exception("boom")

            # Act
            self.service.approve_content(self.post, self.moderator)

        # Assert
        self.post.refresh_from_db()
        self.assertEqual(self.post.status, ResearchhubPost.APPROVED)

    def _pending_paper(self):
        paper = create_paper(uploaded_by=self.author)
        paper.status = Paper.PENDING
        paper.save(update_fields=["status"])
        return paper

    def test_approve_paper_marks_reviewed_and_notifies(self):
        # Arrange
        paper = self._pending_paper()

        # Act
        self.service.approve_content(paper, self.moderator)

        # Assert
        paper.refresh_from_db()
        self.assertEqual(paper.status, Paper.APPROVED)
        self.assertEqual(paper.reviewed_by, self.moderator)
        self.assertIsNotNone(paper.reviewed_date)
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
        self.assertEqual(paper.status, Paper.DECLINED)
        self.assertTrue(paper.is_removed)
        self.assertTrue(paper.unified_document.is_removed)
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
