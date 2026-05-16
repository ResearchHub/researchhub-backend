from datetime import timedelta
from io import StringIO

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from discussion.models import Vote
from purchase.related_models.grant_model import Grant
from research_ai.models import Expert
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from risk_score.constants import DEFAULT_SCORE
from risk_score.models import RiskScoreEvent
from risk_score.services import RiskScoreService
from user.models import UserVerification
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType
DELTAS = RiskScoreEvent.DELTAS


class BackfillOneTimeSignalTests(TestCase):
    def setUp(self):
        self.user = create_user(email="backfill@test.com")

    def _call(self, *args, **kwargs):
        out = StringIO()
        call_command("backfill_risk_scores", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_expert_finder_signal(self):
        # Arrange
        Expert.objects.create(email=self.user.email, registered_user=self.user)

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.EXPERT_FINDER_SIGNUP
            ).exists()
        )

    def test_google_signup_signal(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-123"
        )

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.GOOGLE_SIGNUP
            ).exists()
        )

    def test_edu_email_signal(self):
        # Arrange
        self.user.email = "scholar@stanford.edu"
        self.user.save(update_fields=["email"])

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.EDU_EMAIL_SIGNUP
            ).exists()
        )

    def test_orcid_verified_edu_signal(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user,
            provider="orcid",
            uid="0000-0001-2345-6789",
            extra_data={"verified_edu_emails": ["user@mit.edu"]},
        )

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.ORCID_VERIFIED_EDU
            ).exists()
        )

    def test_persona_verified_signal(self):
        # Arrange
        UserVerification.objects.create(
            user=self.user,
            first_name="Test",
            last_name="User",
            status=UserVerification.Status.APPROVED,
            verified_by=UserVerification.Type.PERSONA,
            external_id="inq_123",
        )

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.PERSONA_VERIFIED_WHITELISTED
            ).exists()
        )

    def test_account_age_bonus_signal(self):
        # Arrange
        self.user.date_joined = timezone.now() - timedelta(days=91)
        self.user.save(update_fields=["date_joined"])

        # Act
        self._call()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_account_age_bonus_not_applied_for_new_accounts(self):
        # Act
        self._call()

        # Assert
        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_idempotent_on_repeated_runs(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-456"
        )
        self._call()

        # Act
        self._call()

        # Assert
        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.GOOGLE_SIGNUP
            ).count(),
            1,
        )

    def test_dry_run_does_not_write(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-dry"
        )

        # Act
        output = self._call("--dry-run")

        # Assert
        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())
        self.assertIn("DRY RUN", output)

    def test_inactive_users_skipped(self):
        # Arrange
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-inactive"
        )

        # Act
        self._call()

        # Assert
        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())


class BackfillHistoricalActionsTests(TestCase):
    def setUp(self):
        self.user = create_user(email="historical@test.com")
        self.post = create_post(created_by=self.user)

    def _call(self, *args, **kwargs):
        out = StringIO()
        call_command("backfill_risk_scores", *args, stdout=out, **kwargs)
        return out.getvalue()

    def test_approved_grant_counted(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )

        # Act
        self._call()

        # Assert
        backfill_event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BACKFILL
        )
        self.assertEqual(backfill_event.delta, DELTAS[EventType.WORK_APPROVED])

    def test_declined_grant_counted(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.DECLINED,
        )

        # Act
        self._call()

        # Assert
        backfill_event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BACKFILL
        )
        self.assertEqual(backfill_event.delta, DELTAS[EventType.WORK_DECLINED])

    def test_censored_comment_counted(self):
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.user,
        )
        RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            is_removed=True,
        )

        # Act
        self._call()

        # Assert
        backfill_event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BACKFILL
        )
        self.assertEqual(backfill_event.delta, DELTAS[EventType.CONTENT_CENSORED])

    def test_upvotes_on_comments_counted(self):
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=thread, created_by=self.user
        )
        voter = create_user(email="voter@test.com")
        Vote.objects.create(
            content_type=ContentType.objects.get_for_model(comment),
            object_id=comment.id,
            created_by=voter,
            vote_type=Vote.UPVOTE,
        )

        # Act
        self._call()

        # Assert
        backfill_event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BACKFILL
        )
        self.assertEqual(backfill_event.delta, DELTAS[EventType.CONTENT_UPVOTED])

    def test_multiple_actions_aggregate(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=2000,
            description="Test 2",
            status=Grant.DECLINED,
        )

        # Act
        self._call()

        # Assert
        backfill_event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.BACKFILL
        )
        expected = DELTAS[EventType.WORK_APPROVED] + DELTAS[EventType.WORK_DECLINED]
        self.assertEqual(backfill_event.delta, expected)

    def test_backfill_recomputed_on_repeat_run(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )
        self._call()

        # Add another grant and re-run
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=2000,
            description="Test 2",
            status=Grant.OPEN,
        )

        # Act
        self._call()

        # Assert
        backfill_events = RiskScoreEvent.objects.filter(
            user=self.user, event_type=EventType.BACKFILL
        )
        self.assertEqual(backfill_events.count(), 1)
        self.assertEqual(
            backfill_events.first().delta, 2 * DELTAS[EventType.WORK_APPROVED]
        )

    def test_score_reflects_combined_signals_and_history(self):
        # Arrange
        SocialAccount.objects.create(
            user=self.user, provider="google", uid="google-combined"
        )
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )

        # Act
        self._call()

        # Assert
        expected = (
            DEFAULT_SCORE
            + DELTAS[EventType.GOOGLE_SIGNUP]
            + DELTAS[EventType.WORK_APPROVED]
        )
        self.assertEqual(RiskScoreService().get_score(self.user), expected)

    def test_no_backfill_event_when_delta_is_zero(self):
        # Act (user has no historical actions)
        self._call()

        # Assert
        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.BACKFILL
            ).exists()
        )
