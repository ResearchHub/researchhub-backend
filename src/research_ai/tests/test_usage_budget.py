from threading import Event, Thread

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework import status
from rest_framework.test import APIClient

from research_ai.models import Expert, ExpertSearch, LLMUsageEvent
from research_ai.services.agent.types import TurnUsage
from research_ai.services.usage_budget import (
    UsageLimitExceededError,
    UsageWorkInProgressError,
    atomic_turn_admission,
    budget_status,
    check_turn_admission,
    record,
    resolve_ai_tier,
)
from user.constants.gatekeeper_constants import RESEARCH_AI_UNLIMITED
from user.related_models.gatekeeper_model import Gatekeeper
from user.tests.helpers import create_random_authenticated_user


class TierResolutionTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("budget-tier")

    def test_blocked_precedes_all_other_tiers(self):
        # Arrange
        self.user.is_staff = True
        self.user.probable_spammer = True
        self.user.save(update_fields=["is_staff", "probable_spammer"])

        # Act / Assert
        self.assertEqual(resolve_ai_tier(self.user).name, "blocked")

    def test_staff_and_gatekeeper_overrides_are_unlimited(self):
        # Arrange / Act / Assert
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.assertEqual(resolve_ai_tier(self.user).name, "unlimited")

        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        Gatekeeper.objects.create(user=self.user, type=RESEARCH_AI_UNLIMITED)
        self.assertEqual(resolve_ai_tier(self.user).name, "unlimited")

    def test_moderator_and_registered_expert_are_privileged(self):
        # Arrange / Act / Assert
        self.user.moderator = True
        self.user.save(update_fields=["moderator"])
        self.assertEqual(resolve_ai_tier(self.user).name, "privileged")

        self.user.moderator = False
        self.user.save(update_fields=["moderator"])
        Expert.objects.create(email="invitee@example.org", registered_user=self.user)
        self.assertEqual(resolve_ai_tier(self.user).name, "privileged")


class UsageBudgetTests(TestCase):
    MODEL = "openrouter:deepseek/deepseek-v4-pro-0813"

    def setUp(self):
        self.user = create_random_authenticated_user("budget-usage")

    def test_record_prices_and_status_aggregates_usage(self):
        # Act
        event = record(
            self.user,
            "notebook_chat",
            "openrouter",
            "deepseek/deepseek-v4-pro-0813",
            TurnUsage(input_tokens=1_000, output_tokens=500),
        )
        status = budget_status(self.user)

        # Assert
        self.assertEqual(event.cost_microusd, 1_650)
        self.assertEqual(status.spent_today_microusd, 1_650)
        self.assertEqual(status.turns_used, 1)
        self.assertEqual(status.remaining_microusd, 248_350)

    @override_settings(RESEARCH_AI_TIER_DEFAULT_DAILY_TURN_CAP=1)
    def test_admission_raises_when_daily_turn_cap_is_spent(self):
        # Arrange
        LLMUsageEvent.objects.create(
            user=self.user,
            feature="notebook_chat",
            provider="openrouter",
            model="deepseek/deepseek-v4-pro-0813",
            cost_microusd=1,
        )

        # Act / Assert
        with self.assertRaises(UsageLimitExceededError) as raised:
            check_turn_admission(
                self.user, self.MODEL, effort="none", thinking="disabled"
            )
        self.assertEqual(raised.exception.status.turns_used, 1)

    def test_default_tier_rejects_locked_model(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            check_turn_admission(
                self.user,
                "claude_platform:claude-opus-5",
            )


class AtomicAdmissionTests(TransactionTestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("budget-concurrent")

    def test_concurrent_jobs_cannot_share_the_same_budget_snapshot(self):
        # Arrange
        first_created = Event()
        second_started = Event()
        allow_first_commit = Event()
        errors = []
        admissions = []

        def admit_first():
            close_old_connections()
            user = get_user_model().objects.get(pk=self.user.pk)
            try:
                with atomic_turn_admission(user):
                    ExpertSearch.objects.create(
                        created_by=user,
                        query="first",
                        status=ExpertSearch.Status.PENDING,
                    )
                    first_created.set()
                    allow_first_commit.wait(timeout=10)
            except Exception as error:  # noqa: BLE001 - asserted in main thread
                errors.append(error)
            finally:
                close_old_connections()

        def admit_second():
            first_created.wait(timeout=10)
            close_old_connections()
            user = get_user_model().objects.get(pk=self.user.pk)
            second_started.set()
            try:
                with atomic_turn_admission(user):
                    admissions.append("second")
            except Exception as error:  # noqa: BLE001 - asserted in main thread
                errors.append(error)
            finally:
                close_old_connections()

        first = Thread(target=admit_first)
        second = Thread(target=admit_second)

        # Act
        first.start()
        self.assertTrue(first_created.wait(timeout=10))
        second.start()
        self.assertTrue(second_started.wait(timeout=10))
        allow_first_commit.set()
        first.join(timeout=10)
        second.join(timeout=10)

        # Assert
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(admissions, [])
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], UsageWorkInProgressError)


class UsageBudgetAPITests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("budget-api")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_status_endpoint_returns_meter_shape(self):
        # Act
        response = self.client.get("/api/research_ai/usage-budget/")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            sorted(response.json()),
            [
                "daily_budget",
                "remaining",
                "resets_at",
                "spent_today",
                "tier",
                "turn_cap",
                "turns_used",
            ],
        )
        self.assertEqual(response.json()["tier"], "default")

    @override_settings(RESEARCH_AI_TIER_DEFAULT_DAILY_TURN_CAP=1)
    def test_expert_search_admission_returns_429_status_shape(self):
        # Arrange
        LLMUsageEvent.objects.create(
            user=self.user,
            feature="expert_finder",
            provider="openai",
            model="gpt-5.4-mini",
            cost_microusd=1,
        )

        # Act: admission runs before request-shape validation.
        response = self.client.post(
            "/api/research_ai/expert-finder/searches/", {}, format="json"
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")
        self.assertEqual(response.json()["turns_used"], 1)
        self.assertIn("resets_at", response.json())
