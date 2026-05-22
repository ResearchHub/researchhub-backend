from datetime import timedelta
from unittest.mock import patch

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

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
from user.tasks.risk_score_tasks import apply_account_age_bonus_task
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType
DELTAS = RiskScoreEvent.DELTAS


class GrantSignalTests(TestCase):
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

    def test_approved_records_work_approved(self):
        grant = self._create_grant(status=Grant.PENDING)

        grant.status = Grant.OPEN
        grant.save(update_fields=["status"])

        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.WORK_APPROVED
        )
        self.assertEqual(event.delta, DELTAS[EventType.WORK_APPROVED])
        self.assertEqual(event.source_content_id, grant.pk)

    def test_declined_records_work_declined(self):
        grant = self._create_grant(status=Grant.PENDING)

        grant.status = Grant.DECLINED
        grant.save(update_fields=["status"])

        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.WORK_DECLINED
        )
        self.assertEqual(event.delta, DELTAS[EventType.WORK_DECLINED])

    def test_pending_does_not_record(self):
        self._create_grant(status=Grant.PENDING)

        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())

    def test_idempotent_on_repeated_save(self):
        grant = self._create_grant(status=Grant.OPEN)

        grant.save()

        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.WORK_APPROVED
            ).count(),
            1,
        )


class ContentCensoredSignalTests(TestCase):
    def setUp(self):
        self.user = create_user(email="censor@test.com")
        self.post = create_post(created_by=self.user)

    def _create_comment(self):
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.user,
        )
        return RhCommentModel.objects.create(thread=thread, created_by=self.user)

    def test_comment_censored_records_event(self):
        comment = self._create_comment()

        comment.delete(soft=True)

        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.CONTENT_CENSORED
        )
        self.assertEqual(event.delta, DELTAS[EventType.CONTENT_CENSORED])
        self.assertEqual(event.source_content_id, comment.pk)

    def test_comment_not_removed_does_not_record(self):
        self._create_comment()

        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())

    def test_document_censored_records_event(self):
        doc = self.post.unified_document

        doc.is_removed = True
        doc.save()

        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.CONTENT_CENSORED
        )
        self.assertEqual(event.source_content_id, doc.pk)

    def test_document_censored_idempotent(self):
        doc = self.post.unified_document
        doc.is_removed = True
        doc.save()

        doc.save()

        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.CONTENT_CENSORED
            ).count(),
            1,
        )


class BountySolutionSignalTests(TestCase):
    def setUp(self):
        self.bounty_creator = create_user(email="bounty_creator@test.com")
        self.recipient = create_user(email="recipient@test.com")
        self.post = create_post(created_by=self.bounty_creator)
        ct = ContentType.objects.get_for_model(self.post)
        escrow = Escrow.objects.create(
            created_by=self.bounty_creator,
            hold_type=Escrow.BOUNTY,
            content_type=ct,
            object_id=self.post.id,
        )
        self.bounty = Bounty.objects.create(
            created_by=self.bounty_creator,
            amount=100,
            item_content_type=ct,
            item_object_id=self.post.id,
            unified_document=self.post.unified_document,
            escrow=escrow,
        )

    def _create_solution(self, status=BountySolution.Status.SUBMITTED, **kwargs):
        defaults = {
            "bounty": self.bounty,
            "created_by": self.recipient,
            "content_type": ContentType.objects.get_for_model(self.post),
            "object_id": self.post.id,
            "status": status,
        }
        defaults.update(kwargs)
        return BountySolution.objects.create(**defaults)

    def test_awarded_records_bounty_awarded(self):
        solution = self._create_solution(status=BountySolution.Status.SUBMITTED)

        solution.status = BountySolution.Status.AWARDED
        solution.save(update_fields=["status"])

        event = RiskScoreEvent.objects.get(
            user=self.recipient, event_type=EventType.BOUNTY_AWARDED
        )
        self.assertEqual(event.delta, DELTAS[EventType.BOUNTY_AWARDED])
        self.assertEqual(event.source_content_id, solution.pk)

    def test_submitted_does_not_record(self):
        self._create_solution(status=BountySolution.Status.SUBMITTED)

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=self.recipient, event_type=EventType.BOUNTY_AWARDED
            ).exists()
        )

    @patch.object(User, "is_rh_community_account", return_value=True)
    def test_community_bounty_on_comment_records_assessed(self, mock_rh):
        # Arrange: solution points to a comment with a review
        reviewer = create_user(email="reviewer@test.com")
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.recipient,
        )
        comment = RhCommentModel.objects.create(
            thread=thread, created_by=self.recipient
        )
        Review.objects.create(
            created_by=reviewer,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.pk,
            unified_document=self.post.unified_document,
            is_assessed=False,
        )
        solution = BountySolution.objects.create(
            bounty=self.bounty,
            created_by=self.recipient,
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.pk,
            status=BountySolution.Status.AWARDED,
        )

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=reviewer, event_type=EventType.PEER_REVIEW_ASSESSED
            ).exists()
        )
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.recipient, event_type=EventType.BOUNTY_AWARDED
            ).exists()
        )


class CommunityTipSignalTests(TestCase):
    def setUp(self):
        self.community_user = create_user(email="community@researchhub.com")
        self.comment_author = create_user(email="author@test.com")
        self.reviewer = create_user(email="reviewer@test.com")
        self.post = create_post(created_by=self.comment_author)
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.comment_author,
        )
        self.comment = RhCommentModel.objects.create(
            thread=thread, created_by=self.comment_author
        )
        Review.objects.create(
            created_by=self.reviewer,
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.pk,
            unified_document=self.post.unified_document,
            is_assessed=False,
        )

    def _tip_comment(self, user=None):
        return Purchase.objects.create(
            user=user or self.community_user,
            content_type=ContentType.objects.get_for_model(self.comment),
            object_id=self.comment.pk,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="100",
        )

    @patch.object(User, "is_rh_community_account", return_value=True)
    def test_community_tip_records_tipped_and_assessed(self, mock_rh):
        self._tip_comment()

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.comment_author, event_type=EventType.PEER_REVIEW_TIPPED
            ).exists()
        )
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.reviewer, event_type=EventType.PEER_REVIEW_ASSESSED
            ).exists()
        )

    @patch.object(User, "is_rh_community_account", return_value=False)
    def test_non_community_tip_does_not_record(self, mock_rh):
        regular_user = create_user(email="regular@test.com")
        self._tip_comment(user=regular_user)

        self.assertFalse(RiskScoreEvent.objects.filter(
            user=self.comment_author, event_type=EventType.PEER_REVIEW_TIPPED
        ).exists())
        self.assertFalse(RiskScoreEvent.objects.filter(
            user=self.reviewer, event_type=EventType.PEER_REVIEW_ASSESSED
        ).exists())


class SocialAccountSignalTests(TestCase):
    def setUp(self):
        self.user = create_user(email="social@test.com")

    def test_google_signup_records_event(self):
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-123"
        )

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.GOOGLE_SIGNUP
            ).exists()
        )

    def test_orcid_with_verified_edu_records_event(self):
        SocialAccount.objects.create(
            user=self.user,
            provider="orcid",
            uid="0000-0001-2345-6789",
            extra_data={"verified_edu_emails": ["user@mit.edu"]},
        )

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.ORCID_VERIFIED_EDU
            ).exists()
        )

    def test_orcid_without_verified_edu_does_not_record(self):
        SocialAccount.objects.create(
            user=self.user, provider="orcid", uid="0000-0001-2345-6790", extra_data={}
        )

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.ORCID_VERIFIED_EDU
            ).exists()
        )

    def test_other_provider_does_not_record(self):
        SocialAccount.objects.create(user=self.user, provider="github", uid="gh-123")

        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())


class PersonaVerificationSignalTests(TestCase):
    def setUp(self):
        self.user = create_user(email="persona@test.com")

    def _verify(self, status):
        return UserVerification.objects.create(
            user=self.user,
            first_name="Test",
            last_name="User",
            status=status,
            verified_by=UserVerification.Type.PERSONA,
            external_id="inq_123",
        )

    def test_approved_records_event(self):
        self._verify(UserVerification.Status.APPROVED)

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.PERSONA_VERIFIED_WHITELISTED
            ).exists()
        )

    def test_non_approved_does_not_record(self):
        for status in (UserVerification.Status.PENDING, UserVerification.Status.DECLINED):
            with self.subTest(status=status):
                # Reset: delete existing verification (OneToOne)
                UserVerification.objects.filter(user=self.user).delete()
                RiskScoreEvent.objects.filter(user=self.user).delete()

                self._verify(status)

                self.assertFalse(
                    RiskScoreEvent.objects.filter(user=self.user).exists()
                )


class UserCreatedSignalTests(TestCase):
    def test_edu_email_records_event(self):
        user = User.objects.create(
            first_name="Scholar", last_name="Test",
            email="scholar@stanford.edu", password="test123",
        )

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.EDU_EMAIL_SIGNUP
            ).exists()
        )

    def test_non_edu_email_does_not_record(self):
        user = User.objects.create(
            first_name="Normal", last_name="User",
            email="normal@gmail.com", password="test123",
        )

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.EDU_EMAIL_SIGNUP
            ).exists()
        )

    def test_expert_finder_email_records_event(self):
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

        user = User.objects.create(
            first_name="Expert", last_name="Person",
            email="expert@university.org", password="test123",
        )

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.EXPERT_FINDER_SIGNUP
            ).exists()
        )

    def test_non_expert_email_does_not_record(self):
        user = User.objects.create(
            first_name="Random", last_name="Person",
            email="random@university.org", password="test123",
        )

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.EXPERT_FINDER_SIGNUP
            ).exists()
        )


class AccountAgeBonusTaskTests(TestCase):
    def _create_old_user(self, email="old@test.com", days=91, active=True):
        user = create_user(email=email)
        user.date_joined = timezone.now() - timedelta(days=days)
        user.is_active = active
        user.save(update_fields=["date_joined", "is_active"])
        return user

    def test_grants_bonus_to_eligible_users(self):
        user = self._create_old_user()

        apply_account_age_bonus_task()

        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_skips_new_accounts(self):
        create_user(email="new@test.com")

        apply_account_age_bonus_task()

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_idempotent_on_repeated_runs(self):
        user = self._create_old_user()
        apply_account_age_bonus_task()

        apply_account_age_bonus_task()

        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).count(),
            1,
        )

    def test_skips_inactive_users(self):
        user = self._create_old_user(email="inactive@test.com", active=False)

        apply_account_age_bonus_task()

        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )
