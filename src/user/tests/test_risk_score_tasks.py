from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from user.related_models.risk_score_model import RiskScoreEvent
from user.tasks.risk_score_tasks import apply_account_age_bonus_task
from user.tests.helpers import create_user

EventType = RiskScoreEvent.EventType


class AccountAgeBonusTaskTests(TestCase):
    def _create_aged_user(self, *, email, days=91, active=True):
        user = create_user(email=email)
        user.date_joined = timezone.now() - timedelta(days=days)
        user.is_active = active
        user.save(update_fields=["date_joined", "is_active"])
        return user

    def test_grants_bonus_to_eligible_users(self):
        # Arrange
        user = self._create_aged_user(email="eligible@test.com")

        # Act
        apply_account_age_bonus_task()

        # Assert
        self.assertTrue(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_skips_new_accounts(self):
        # Arrange
        create_user(email="new@test.com")

        # Act
        apply_account_age_bonus_task()

        # Assert
        self.assertFalse(
            RiskScoreEvent.objects.filter(
                event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_no_age_bonus_for_inactive_users(self):
        # Arrange
        user = self._create_aged_user(email="inactive@test.com", active=False)

        # Act
        apply_account_age_bonus_task()

        # Assert
        self.assertFalse(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).exists()
        )

    def test_repeated_runs_are_idempotent(self):
        # Arrange
        user = self._create_aged_user(email="repeat@test.com")

        # Act
        apply_account_age_bonus_task()
        apply_account_age_bonus_task()

        # Assert
        self.assertEqual(
            RiskScoreEvent.objects.filter(
                user=user, event_type=EventType.ACCOUNT_AGE_BONUS
            ).count(),
            1,
        )
