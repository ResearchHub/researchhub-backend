from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from reputation.related_models.bounty import Bounty, BountySolution
from reputation.related_models.escrow import Escrow
from research_ai.models import Expert, ExpertSearch, GeneratedEmail
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from review.models.review_model import Review
from user.models import User, UserVerification
from user.related_models.risk_score_model import RiskScoreEvent
from user.signals.risk_score_signals import on_post_status_changed
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType


class RiskScoreSignalTestCase(TestCase):
    def _events(self, user, event_type=None):
        events = RiskScoreEvent.objects.filter(user=user)
        if event_type is not None:
            events = events.filter(event_type=event_type)
        return events

    def _assert_has_event(self, user, event_type, *, delta=None, source_id=None):
        events = list(self._events(user, event_type))
        self.assertEqual(
            len(events), 1, f"Expected 1 {event_type} event, found {len(events)}"
        )
        event = events[0]
        if delta is not None:
            self.assertEqual(event.delta, delta)
        if source_id is not None:
            self.assertEqual(event.source_content_id, source_id)

    def _assert_no_events(self, user, event_type=None):
        self.assertFalse(self._events(user, event_type).exists())

    def _assert_event_count(self, user, event_type, count):
        self.assertEqual(self._events(user, event_type).count(), count)

    def _create_comment(self, post, author):
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(post),
            object_id=post.id,
            created_by=author,
        )
        return RhCommentModel.objects.create(thread=thread, created_by=author)


class GrantSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.user = create_user(email="grant@test.com")
        self.post = create_post(created_by=self.user)

    def _create_grant(self, status=Grant.PENDING):
        return Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=status,
        )

    def test_open_status_records_work_approved(self):
        # Arrange
        grant = self._create_grant(Grant.PENDING)

        # Act
        grant.status = Grant.OPEN
        grant.save(update_fields=["status"])

        # Assert
        self._assert_has_event(
            self.user,
            EventType.WORK_APPROVED,
            delta=RiskScoreEvent.DELTAS[EventType.WORK_APPROVED],
            source_id=grant.pk,
        )

    def test_declined_status_records_work_declined(self):
        # Arrange
        grant = self._create_grant(Grant.PENDING)

        # Act
        grant.status = Grant.DECLINED
        grant.save(update_fields=["status"])

        # Assert
        self._assert_has_event(
            self.user,
            EventType.WORK_DECLINED,
            delta=RiskScoreEvent.DELTAS[EventType.WORK_DECLINED],
            source_id=grant.pk,
        )

    def test_pending_status_does_not_record(self):
        # Act
        self._create_grant(Grant.PENDING)

        # Assert
        self._assert_no_events(self.user)

    def test_repeated_save_is_idempotent(self):
        # Arrange
        grant = self._create_grant(Grant.OPEN)

        # Act
        grant.save()

        # Assert
        self._assert_event_count(self.user, EventType.WORK_APPROVED, 1)


class ContentCensoredSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.user = create_user(email="censor@test.com")
        self.post = create_post(created_by=self.user)

    def test_comment_censored_records_event(self):
        # Arrange
        comment = self._create_comment(self.post, self.user)

        # Act
        comment.delete(soft=True)

        # Assert
        self._assert_has_event(
            self.user,
            EventType.CONTENT_CENSORED,
            delta=RiskScoreEvent.DELTAS[EventType.CONTENT_CENSORED],
            source_id=comment.pk,
        )

    def test_comment_not_removed_does_not_record(self):
        # Act
        self._create_comment(self.post, self.user)

        # Assert
        self._assert_no_events(self.user)

    def test_document_censored_records_event(self):
        # Arrange
        document = self.post.unified_document

        # Act
        document.is_removed = True
        document.save()

        # Assert
        self._assert_has_event(
            self.user, EventType.CONTENT_CENSORED, source_id=document.pk
        )

    def test_document_censored_is_idempotent(self):
        # Arrange
        document = self.post.unified_document
        document.is_removed = True
        document.save()

        # Act
        document.save()

        # Assert
        self._assert_event_count(self.user, EventType.CONTENT_CENSORED, 1)


class BountySolutionSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.bounty_creator = create_user(email="bounty_creator@test.com")
        self.recipient = create_user(email="recipient@test.com")
        self.post = create_post(created_by=self.bounty_creator)
        self.post_content_type = ContentType.objects.get_for_model(self.post)
        escrow = Escrow.objects.create(
            created_by=self.bounty_creator,
            hold_type=Escrow.BOUNTY,
            content_type=self.post_content_type,
            object_id=self.post.id,
        )
        self.bounty = Bounty.objects.create(
            created_by=self.bounty_creator,
            amount=100,
            item_content_type=self.post_content_type,
            item_object_id=self.post.id,
            unified_document=self.post.unified_document,
            escrow=escrow,
        )

    def _create_solution(
        self,
        *,
        status=BountySolution.Status.SUBMITTED,
        content_type=None,
        object_id=None,
    ):
        return BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.recipient,
            content_type=content_type or self.post_content_type,
            object_id=self.post.id if object_id is None else object_id,
            status=status,
        )

    def test_awarded_solution_records_bounty_awarded(self):
        # Arrange
        solution = self._create_solution(status=BountySolution.Status.SUBMITTED)

        # Act
        solution.status = BountySolution.Status.AWARDED
        solution.save(update_fields=["status"])

        # Assert
        self._assert_has_event(
            self.recipient,
            EventType.BOUNTY_AWARDED,
            delta=RiskScoreEvent.DELTAS[EventType.BOUNTY_AWARDED],
            source_id=solution.pk,
        )

    def test_submitted_solution_does_not_record(self):
        # Act
        self._create_solution(status=BountySolution.Status.SUBMITTED)

        # Assert
        self._assert_no_events(self.recipient, EventType.BOUNTY_AWARDED)

    @patch.object(User, "is_rh_community_account", return_value=True)
    def test_community_bounty_on_comment_records_review_assessment(self, mock_rh):
        # Arrange
        reviewer = create_user(email="reviewer@test.com")
        comment = self._create_comment(self.post, self.recipient)
        comment_content_type = ContentType.objects.get_for_model(comment)
        Review.objects.create(
            created_by=reviewer,
            content_type=comment_content_type,
            object_id=comment.pk,
            unified_document=self.post.unified_document,
            is_assessed=False,
        )

        # Act
        self._create_solution(
            status=BountySolution.Status.AWARDED,
            content_type=comment_content_type,
            object_id=comment.pk,
        )

        # Assert
        self._assert_has_event(reviewer, EventType.PEER_REVIEW_ASSESSED)
        self._assert_has_event(self.recipient, EventType.BOUNTY_AWARDED)


class CommunityTipSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.community_user = create_user(email="community@researchhub.com")
        self.author = create_user(email="author@test.com")
        self.reviewer = create_user(email="reviewer@test.com")
        self.post = create_post(created_by=self.author)
        self.comment = self._create_comment(self.post, self.author)
        self.comment_content_type = ContentType.objects.get_for_model(self.comment)
        Review.objects.create(
            created_by=self.reviewer,
            content_type=self.comment_content_type,
            object_id=self.comment.pk,
            unified_document=self.post.unified_document,
            is_assessed=False,
        )

    def _create_tip(self, user=None):
        return Purchase.objects.create(
            user=user or self.community_user,
            content_type=self.comment_content_type,
            object_id=self.comment.pk,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="100",
        )

    @patch.object(User, "is_rh_community_account", return_value=True)
    def test_community_tip_records_tipped_and_assessed(self, mock_rh):
        # Act
        self._create_tip()

        # Assert
        self._assert_has_event(self.author, EventType.PEER_REVIEW_TIPPED)
        self._assert_has_event(self.reviewer, EventType.PEER_REVIEW_ASSESSED)

    @patch.object(User, "is_rh_community_account", return_value=False)
    def test_non_community_tip_does_not_record(self, mock_rh):
        # Arrange
        regular_user = create_user(email="regular@test.com")

        # Act
        self._create_tip(user=regular_user)

        # Assert
        self._assert_no_events(self.author, EventType.PEER_REVIEW_TIPPED)
        self._assert_no_events(self.reviewer, EventType.PEER_REVIEW_ASSESSED)


class SocialAccountSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.user = create_user(email="social@test.com")

    def test_google_signup_records_event(self):
        # Act
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-123"
        )

        # Assert
        self._assert_has_event(self.user, EventType.GOOGLE_SIGNUP)

    def test_orcid_with_verified_edu_records_event(self):
        # Act
        SocialAccount.objects.create(
            user=self.user,
            provider="orcid",
            uid="0000-0001-2345-6789",
            extra_data={"verified_edu_emails": ["user@mit.edu"]},
        )

        # Assert
        self._assert_has_event(self.user, EventType.ORCID_VERIFIED_EDU)

    def test_orcid_without_verified_edu_does_not_record(self):
        # Act
        SocialAccount.objects.create(
            user=self.user,
            provider="orcid",
            uid="0000-0001-2345-6790",
            extra_data={},
        )

        # Assert
        self._assert_no_events(self.user, EventType.ORCID_VERIFIED_EDU)

    def test_unrelated_provider_does_not_record(self):
        # Act
        SocialAccount.objects.create(user=self.user, provider="github", uid="gh-123")

        # Assert
        self._assert_no_events(self.user)


class PersonaVerificationSignalTests(RiskScoreSignalTestCase):
    def setUp(self):
        self.user = create_user(email="persona@test.com")

    def _create_verification(self, status):
        return UserVerification.objects.create(
            user=self.user,
            first_name="Test",
            last_name="User",
            status=status,
            verified_by=UserVerification.Type.PERSONA,
            external_id="inq_123",
        )

    def test_approved_verification_records_event(self):
        # Act
        self._create_verification(UserVerification.Status.APPROVED)

        # Assert
        self._assert_has_event(self.user, EventType.PERSONA_VERIFIED_WHITELISTED)

    def test_pending_verification_does_not_record(self):
        # Act
        self._create_verification(UserVerification.Status.PENDING)

        # Assert
        self._assert_no_events(self.user)

    def test_declined_verification_does_not_record(self):
        # Act
        self._create_verification(UserVerification.Status.DECLINED)

        # Assert
        self._assert_no_events(self.user)


class UserCreatedSignalTests(RiskScoreSignalTestCase):
    @classmethod
    def setUpTestData(cls):
        admin = create_user(email="admin@test.com")
        search = ExpertSearch.objects.create(created_by=admin, query="ml")
        Expert.objects.create(
            email="expert@university.org", first_name="E", last_name="P"
        )
        GeneratedEmail.objects.create(
            expert_email="expert@university.org",
            expert_search=search,
            created_by=admin,
        )

    def test_edu_email_records_event(self):
        # Act
        user = create_user(email="scholar@stanford.edu")

        # Assert
        self._assert_has_event(user, EventType.EDU_EMAIL_SIGNUP)

    def test_non_edu_email_does_not_record(self):
        # Act
        user = create_user(email="normal@gmail.com")

        # Assert
        self._assert_no_events(user, EventType.EDU_EMAIL_SIGNUP)

    def test_expert_finder_email_records_event(self):
        # Act
        user = create_user(email="expert@university.org")

        # Assert
        self._assert_has_event(user, EventType.EXPERT_FINDER_SIGNUP)

    def test_non_expert_email_does_not_record(self):
        # Act
        user = create_user(email="random@university.org")

        # Assert
        self._assert_no_events(user, EventType.EXPERT_FINDER_SIGNUP)


class PostStatusChangedSignalTests(RiskScoreSignalTestCase):
    """Tests for on_post_status_changed signal. The `status` field will be
    added to ResearchhubPost in a future PR; we test the handler logic by
    invoking it directly with a mock status attribute."""

    def setUp(self):
        self.user = create_user(email="postauthor@test.com")
        self.post = create_post(created_by=self.user)

    def test_approved_status_records_work_approved(self):
        # Simulate the future status field
        self.post.status = "APPROVED"

        # Act
        on_post_status_changed(
            sender=type(self.post), instance=self.post, created=False
        )

        # Assert
        self._assert_has_event(
            self.user,
            EventType.WORK_APPROVED,
            delta=RiskScoreEvent.DELTAS[EventType.WORK_APPROVED],
            source_id=self.post.pk,
        )

    def test_declined_status_records_work_declined(self):
        self.post.status = "DECLINED"

        # Act
        on_post_status_changed(
            sender=type(self.post), instance=self.post, created=False
        )

        # Assert
        self._assert_has_event(
            self.user,
            EventType.WORK_DECLINED,
            delta=RiskScoreEvent.DELTAS[EventType.WORK_DECLINED],
            source_id=self.post.pk,
        )

    def test_pending_status_does_not_record(self):
        self.post.status = "PENDING"

        # Act
        on_post_status_changed(
            sender=type(self.post), instance=self.post, created=False
        )

        # Assert
        self._assert_no_events(self.user)

    def test_no_status_field_does_not_record(self):
        # Act - no status attribute set, simulating current state
        on_post_status_changed(
            sender=type(self.post), instance=self.post, created=False
        )

        # Assert
        self._assert_no_events(self.user)
