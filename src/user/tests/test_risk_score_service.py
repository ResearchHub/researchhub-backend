from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from user.constants.risk_score_constants import (
    DEFAULT_SCORE,
    RESTRICTED_THRESHOLD,
    TRUSTED_THRESHOLD,
)
from user.related_models.risk_score_model import RiskScore, RiskScoreEvent
from user.services.risk_score_service import RiskScoreService
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType


class RiskScoreServiceTests(TestCase):
    def setUp(self):
        self.service = RiskScoreService()
        self.user = create_user(email="risk@test.com")

    def test_get_score_returns_default_when_no_record(self):
        # Act
        result = self.service.get_score(self.user)

        # Assert
        self.assertEqual(result, DEFAULT_SCORE)
        self.assertFalse(RiskScore.objects.filter(user=self.user).exists())

    def test_get_score_returns_existing(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=42)

        # Act
        result = self.service.get_score(self.user)

        # Assert
        self.assertEqual(result, 42)

    def test_trusted_at_boundary(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=TRUSTED_THRESHOLD)

        # Act
        result = self.service.is_trusted(self.user)

        # Assert
        self.assertTrue(result)

    def test_not_trusted_past_boundary(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=TRUSTED_THRESHOLD - 1)

        # Act
        result = self.service.is_trusted(self.user)

        # Assert
        self.assertFalse(result)

    def test_restricted_at_boundary(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=RESTRICTED_THRESHOLD)

        # Act
        result = self.service.is_restricted(self.user)

        # Assert
        self.assertTrue(result)

    def test_not_restricted_past_boundary(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=RESTRICTED_THRESHOLD + 1)

        # Act
        result = self.service.is_restricted(self.user)

        # Assert
        self.assertFalse(result)

    def test_record_event_applies_default_delta(self):
        # Act
        event = self.service.record_event(self.user, EventType.WORK_APPROVED)

        # Assert
        self.assertEqual(event.delta, 50)
        self.assertEqual(self.service.get_score(self.user), DEFAULT_SCORE + 50)

    def test_record_event_explicit_delta_overrides_default(self):
        # Act
        event = self.service.record_event(self.user, EventType.WORK_APPROVED, delta=-5)

        # Assert
        self.assertEqual(event.delta, -5)
        self.assertEqual(self.service.get_score(self.user), DEFAULT_SCORE - 5)

    def test_record_event_defaults_action_date_to_now(self):
        # Act
        event = self.service.record_event(self.user, EventType.WORK_APPROVED)

        # Assert
        self.assertAlmostEqual(
            event.action_date, timezone.now(), delta=timedelta(seconds=5)
        )

    def test_record_event_uses_explicit_action_date(self):
        # Arrange
        occurred_at = timezone.now() - timedelta(days=30)

        # Act
        event = self.service.record_event(
            self.user, EventType.WORK_APPROVED, action_date=occurred_at
        )

        # Assert
        self.assertEqual(event.action_date, occurred_at)
        self.assertGreater(event.created_date, occurred_at)

    def test_record_event_raises_for_unknown_type(self):
        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.record_event(self.user, "UNKNOWN_TYPE")

    def test_record_event_stores_source(self):
        # Arrange
        source_obj = RiskScore.objects.create(user=self.user, score=DEFAULT_SCORE)

        # Act
        event = self.service.record_event(
            self.user, EventType.WORK_APPROVED, source=source_obj
        )

        # Assert
        self.assertEqual(event.source_content_id, source_obj.pk)
        self.assertIsNotNone(event.source_content_type)

    def test_record_event_accumulates(self):
        # Act
        self.service.record_event(self.user, EventType.WORK_DECLINED)
        self.service.record_event(self.user, EventType.WORK_DECLINED)

        # Assert
        self.assertEqual(self.service.get_score(self.user), DEFAULT_SCORE - 40)

    def test_one_time_event_duplicate_ignored(self):
        # Arrange
        self.service.record_event(self.user, EventType.EXPERT_FINDER_SIGNUP)

        # Act
        result = self.service.record_event(self.user, EventType.EXPERT_FINDER_SIGNUP)

        # Assert
        self.assertIsNone(result)
        self.assertEqual(RiskScoreEvent.objects.filter(user=self.user).count(), 1)

    def test_source_duplicate_ignored(self):
        # Arrange
        source_obj = RiskScore.objects.create(user=self.user, score=DEFAULT_SCORE)
        self.service.record_event(self.user, EventType.WORK_APPROVED, source=source_obj)

        # Act
        result = self.service.record_event(
            self.user, EventType.WORK_APPROVED, source=source_obj
        )

        # Assert
        self.assertIsNone(result)
        self.assertEqual(RiskScoreEvent.objects.filter(user=self.user).count(), 1)

    def test_score_derived_from_ledger_not_incremental(self):
        # Arrange - manually corrupt the score
        self.service.record_event(self.user, EventType.WORK_APPROVED)
        RiskScore.objects.filter(user=self.user).update(score=999)

        # Act - next event forces recalculation from ledger
        self.service.record_event(self.user, EventType.WORK_DECLINED)

        # Assert - score reflects full ledger, not 999 - 20
        self.assertEqual(self.service.get_score(self.user), DEFAULT_SCORE + 50 - 20)
