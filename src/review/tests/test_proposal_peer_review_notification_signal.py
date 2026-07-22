from decimal import Decimal
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from notification.models import Notification
from purchase.models import Grant, GrantApplication
from researchhub_comment.tests.helpers import create_rh_comment
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    GRANT,
    PREREGISTRATION,
)
from review.models import Review
from user.tests.helpers import create_random_default_user


class ProposalPeerReviewNotificationSignalTests(TestCase):
    def setUp(self):
        # Arrange
        self.owner = create_random_default_user("rfp_owner")
        self.applicant = create_random_default_user("proposal_author")
        self.reviewer = create_random_default_user("peer_reviewer")

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
            title="Reviewed Proposal",
        )
        self.application = GrantApplication.objects.create(
            grant=self.grant,
            preregistration_post=self.proposal,
            applicant=self.applicant,
        )
        # Application create also fires GRANT_APPLICATION_SUBMITTED; clear it.
        Notification.objects.all().delete()

        self.comment = create_rh_comment(
            created_by=self.reviewer,
            post=self.proposal,
        )
        self.comment_ct = ContentType.objects.get_for_model(self.comment)

    def test_creates_notification_for_grant_owner(self):
        # Act
        review = Review.objects.create(
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            unified_document=self.proposal.unified_document,
            score=8,
        )

        # Assert
        notification = Notification.objects.get(
            notification_type=Notification.PROPOSAL_PEER_REVIEW,
            recipient=self.owner,
        )
        self.assertEqual(notification.action_user, self.reviewer)
        self.assertEqual(notification.object_id, review.id)
        self.assertEqual(
            notification.unified_document_id, self.proposal.unified_document_id
        )

    def test_no_notification_without_grant_application(self):
        # Arrange
        standalone = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Standalone Proposal",
        )
        comment = create_rh_comment(created_by=self.reviewer, post=standalone)

        # Act
        Review.objects.create(
            created_by=self.reviewer,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            unified_document=standalone.unified_document,
            score=7,
        )

        # Assert
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.PROPOSAL_PEER_REVIEW
            ).exists()
        )

    def test_no_notification_on_review_update(self):
        # Arrange
        review = Review.objects.create(
            created_by=self.reviewer,
            content_type=self.comment_ct,
            object_id=self.comment.id,
            unified_document=self.proposal.unified_document,
            score=8,
        )
        Notification.objects.filter(
            notification_type=Notification.PROPOSAL_PEER_REVIEW
        ).delete()

        # Act — mirrors AI update_or_create updating an existing score
        Review.objects.update_or_create(
            content_type=self.comment_ct,
            object_id=self.comment.id,
            defaults={
                "unified_document": self.proposal.unified_document,
                "created_by": self.reviewer,
                "score": 9,
            },
        )

        # Assert
        self.assertFalse(
            Notification.objects.filter(
                notification_type=Notification.PROPOSAL_PEER_REVIEW
            ).exists()
        )
        review.refresh_from_db()
        self.assertEqual(review.score, 9)


class ProposalPeerReviewNotificationDispatchTests(TestCase):
    def setUp(self):
        # Arrange
        self.owner = create_random_default_user("rfp_owner_tx")
        self.applicant = create_random_default_user("proposal_author_tx")
        self.reviewer = create_random_default_user("peer_reviewer_tx")

        grant_post = create_post(created_by=self.owner, document_type=GRANT)
        grant = Grant.objects.create(
            created_by=self.owner,
            unified_document=grant_post.unified_document,
            amount=Decimal("10000.00"),
            currency="USD",
            organization="Test Org",
            description="Test grant",
            status=Grant.OPEN,
        )
        proposal = create_post(
            created_by=self.applicant,
            document_type=PREREGISTRATION,
            title="Reviewed Proposal TX",
        )
        GrantApplication.objects.create(
            grant=grant,
            preregistration_post=proposal,
            applicant=self.applicant,
        )
        Notification.objects.all().delete()

        self.comment = create_rh_comment(created_by=self.reviewer, post=proposal)
        self.comment_ct = ContentType.objects.get_for_model(self.comment)
        self.proposal_ud = proposal.unified_document

    @patch.object(Notification, "send_notification")
    def test_notification_dispatched_on_commit(self, mock_send):
        # Act
        with self.captureOnCommitCallbacks(execute=True):
            Review.objects.create(
                created_by=self.reviewer,
                content_type=self.comment_ct,
                object_id=self.comment.id,
                unified_document=self.proposal_ud,
                score=8,
            )

        # Assert
        mock_send.assert_called_once()
