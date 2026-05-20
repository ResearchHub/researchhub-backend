from datetime import timedelta
from io import StringIO

from allauth.socialaccount.models import SocialAccount
from django.contrib.contenttypes.models import ContentType
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from purchase.related_models.grant_model import Grant
from purchase.related_models.purchase_model import Purchase
from research_ai.models import Expert
from researchhub_comment.related_models.rh_comment_model import RhCommentModel
from researchhub_comment.related_models.rh_comment_thread_model import (
    RhCommentThreadModel,
)
from researchhub_document.helpers import create_post
from user.constants.risk_score_constants import DEFAULT_SCORE
from user.models import UserVerification
from user.related_models.risk_score_model import RiskScoreEvent
from user.related_models.user_model import FOUNDATION_EMAIL
from user.services.risk_score_service import RiskScoreService
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType
DELTAS = RiskScoreEvent.DELTAS


class BackfillCommandMixin:
    def _call(self, *args, **kwargs):
        out = StringIO()
        call_command("backfill_risk_scores", *args, stdout=out, **kwargs)
        return out.getvalue()


class BackfillOneTimeSignalTests(BackfillCommandMixin, TestCase):
    def setUp(self):
        self.user = create_user(email="backfill@test.com")

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


class BackfillHistoricalActionsTests(BackfillCommandMixin, TestCase):
    def setUp(self):
        self.user = create_user(email="historical@test.com")
        self.post = create_post(created_by=self.user)

    def test_approved_grant_creates_work_approved_event(self):
        # Arrange
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )

        # Act
        self._call()

        # Assert
        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.WORK_APPROVED
        )
        self.assertEqual(event.delta, DELTAS[EventType.WORK_APPROVED])
        self.assertEqual(event.source_content_id, grant.pk)

    def test_declined_grant_creates_work_declined_event(self):
        # Arrange
        grant = Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.DECLINED,
        )

        # Act
        self._call()

        # Assert
        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.WORK_DECLINED
        )
        self.assertEqual(event.delta, DELTAS[EventType.WORK_DECLINED])
        self.assertEqual(event.source_content_id, grant.pk)

    def test_censored_comment_creates_content_censored_event(self):
        # Arrange
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(
            thread=thread,
            created_by=self.user,
            is_removed=True,
        )

        # Act
        self._call()

        # Assert
        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.CONTENT_CENSORED
        )
        self.assertEqual(event.delta, DELTAS[EventType.CONTENT_CENSORED])
        self.assertEqual(event.source_content_id, comment.pk)

    def test_multiple_grants_create_individual_events(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test 1",
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
        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.WORK_APPROVED
            ).count(),
            1,
        )
        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.WORK_DECLINED
            ).count(),
            1,
        )

    def test_historical_events_idempotent_on_repeat_run(self):
        # Arrange
        Grant.objects.create(
            created_by=self.user,
            unified_document=self.post.unified_document,
            amount=1000,
            description="Test",
            status=Grant.OPEN,
        )
        self._call()

        # Act
        self._call()

        # Assert
        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=self.user, event_type=EventType.WORK_APPROVED
            ).count(),
            1,
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

    def test_inactive_user_historical_events_skipped(self):
        # Arrange
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
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
        self.assertFalse(RiskScoreEvent.objects.filter(user=self.user).exists())

    def test_foundation_tip_creates_peer_review_tipped_event(self):
        # Arrange
        community = create_user(email=FOUNDATION_EMAIL)
        comment_ct = ContentType.objects.get_for_model(RhCommentModel)
        thread = RhCommentThreadModel.objects.create(
            content_type=ContentType.objects.get_for_model(self.post),
            object_id=self.post.id,
            created_by=self.user,
        )
        comment = RhCommentModel.objects.create(thread=thread, created_by=self.user)
        purchase = Purchase.objects.create(
            user=community,
            content_type=comment_ct,
            object_id=comment.pk,
            purchase_method=Purchase.OFF_CHAIN,
            purchase_type=Purchase.BOOST,
            amount="100",
            paid_status="PAID",
        )

        # Act
        self._call()

        # Assert
        event = RiskScoreEvent.objects.get(
            user=self.user, event_type=EventType.PEER_REVIEW_TIPPED
        )
        self.assertEqual(event.source_content_id, purchase.pk)
