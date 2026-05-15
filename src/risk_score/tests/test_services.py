from django.test import TestCase

from risk_score.constants import (
    DAILY_DOWNVOTE_SCORE_CAP,
    DAILY_UPVOTE_SCORE_CAP,
    DEFAULT_SCORE,
    RESTRICTED_THRESHOLD,
    SCORE_CEILING,
    SCORE_FLOOR,
    TRUSTED_THRESHOLD,
)
from risk_score.models import RiskScore, RiskScoreEvent
from risk_score.services import RiskScoreService
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType


class RiskScoreServiceTests(TestCase):
    def setUp(self):
        self.service = RiskScoreService()
        self.user = create_user(email="risk@test.com")

    def test_get_score_creates_default(self):
        # Act
        result = self.service.get_score(self.user)

        # Assert
        self.assertEqual(result, DEFAULT_SCORE)

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
        RiskScore.objects.create(user=self.user, score=TRUSTED_THRESHOLD + 1)

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
        RiskScore.objects.create(user=self.user, score=RESTRICTED_THRESHOLD - 1)

        # Act
        result = self.service.is_restricted(self.user)

        # Assert
        self.assertFalse(result)

    def test_record_event_applies_default_delta(self):
        # Act
        event = self.service.record_event(self.user, EventType.WORK_APPROVED)

        # Assert
        self.assertEqual(event.delta, -50)
        self.assertEqual(event.score_after, DEFAULT_SCORE - 50)

    def test_record_event_explicit_delta_overrides_default(self):
        # Act
        event = self.service.record_event(
            self.user, EventType.WORK_APPROVED, delta=-5
        )

        # Assert
        self.assertEqual(event.delta, -5)
        self.assertEqual(event.score_after, DEFAULT_SCORE - 5)

    def test_record_event_raises_when_delta_required(self):
        # Act & Assert
        with self.assertRaises(ValueError):
            self.service.record_event(self.user, EventType.BACKFILL)

    def test_record_event_stores_metadata(self):
        # Arrange
        meta = {"reason": "test"}

        # Act
        event = self.service.record_event(
            self.user, EventType.WORK_DECLINED, metadata=meta
        )

        # Assert
        self.assertEqual(event.metadata, meta)

    def test_record_event_stores_source(self):
        # Arrange
        source_obj = RiskScore.objects.create(user=self.user, score=DEFAULT_SCORE)

        # Act
        event = self.service.record_event(
            self.user, EventType.WORK_APPROVED, source=source_obj
        )

        # Assert
        self.assertEqual(event.source_object_id, source_obj.pk)
        self.assertIsNotNone(event.source_content_type)

    def test_record_event_accumulates(self):
        # Arrange
        self.service.record_event(self.user, EventType.WORK_DECLINED)
        self.service.record_event(self.user, EventType.WORK_DECLINED)

        # Act
        result = self.service.get_score(self.user)

        # Assert
        self.assertEqual(result, DEFAULT_SCORE + 40)

    def test_clamps_to_floor(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=10)

        # Act
        event = self.service.record_event(self.user, EventType.BACKFILL, delta=-50)

        # Assert
        self.assertEqual(event.score_after, SCORE_FLOOR)

    def test_clamps_to_ceiling(self):
        # Arrange
        RiskScore.objects.create(user=self.user, score=SCORE_CEILING - 5)

        # Act
        event = self.service.record_event(self.user, EventType.WORK_DECLINED)

        # Assert
        self.assertEqual(event.score_after, SCORE_CEILING)

    def test_upvote_cap_enforced(self):
        # Arrange
        for _ in range(DAILY_UPVOTE_SCORE_CAP):
            self.service.record_event(self.user, EventType.CONTENT_UPVOTED)

        # Act
        result = self.service.record_event(self.user, EventType.CONTENT_UPVOTED)

        # Assert
        self.assertIsNone(result)
        self.assertEqual(
            self.service.get_score(self.user), DEFAULT_SCORE - DAILY_UPVOTE_SCORE_CAP
        )

    def test_downvote_cap_enforced(self):
        # Arrange
        for _ in range(DAILY_DOWNVOTE_SCORE_CAP):
            self.service.record_event(self.user, EventType.CONTENT_DOWNVOTED)

        # Act
        result = self.service.record_event(self.user, EventType.CONTENT_DOWNVOTED)

        # Assert
        self.assertIsNone(result)
        self.assertEqual(
            self.service.get_score(self.user), DEFAULT_SCORE + DAILY_DOWNVOTE_SCORE_CAP
        )

    def test_one_time_event_duplicate_ignored(self):
        # Arrange
        self.service.record_event(self.user, EventType.EXPERT_FINDER_SIGNUP)

        # Act
        result = self.service.record_event(self.user, EventType.EXPERT_FINDER_SIGNUP)

        # Assert
        self.assertIsNone(result)
        self.assertEqual(RiskScoreEvent.objects.filter(user=self.user).count(), 1)

    def test_recalculate_from_ledger(self):
        # Arrange
        self.service.record_event(self.user, EventType.WORK_APPROVED)
        self.service.record_event(self.user, EventType.WORK_DECLINED)
        RiskScore.objects.filter(user=self.user).update(score=999)

        # Act
        result = self.service.recalculate_from_ledger(self.user)

        # Assert
        self.assertEqual(result, DEFAULT_SCORE - 30)

    def test_recalculate_clamps(self):
        # Arrange
        self.service.record_event(self.user, EventType.BACKFILL, delta=-200)

        # Act
        result = self.service.recalculate_from_ledger(self.user)

        # Assert
        self.assertEqual(result, SCORE_FLOOR)

    def test_recalculate_with_no_events(self):
        # Act
        result = self.service.recalculate_from_ledger(self.user)

        # Assert
        self.assertEqual(result, DEFAULT_SCORE)
