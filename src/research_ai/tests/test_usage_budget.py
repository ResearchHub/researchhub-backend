from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from research_ai.models import AgentConversation, AgentExecution, Expert, LLMUsageEvent
from research_ai.services.agent import AgentService, ProviderError, Toolset
from research_ai.services.agent.model_catalog import ModelOption
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    TextStreamDelta,
    TurnUsage,
)
from research_ai.services.usage_budget import (
    AgentLoopBudgetRecorder,
    BudgetExceededError,
    BudgetStatus,
    ModelNotAllowedError,
    TierPolicy,
    UsageLimitExceededError,
    UsageWorkInProgressError,
    atomic_turn_admission,
    budget_status,
    check_turn_admission,
    record,
    resolve_ai_tier,
)
from research_ai.services.usage_budget import service as usage_budget_service
from research_ai.tests.agent.test_loop import FakeProvider, _build_text_turn
from user.tests.helpers import create_hub_editor, create_random_authenticated_user


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

    def test_inactive_and_removed_users_are_blocked(self):
        # Arrange / Act / Assert
        self.user.is_active = False
        self.assertEqual(resolve_ai_tier(self.user).name, "blocked")

        self.user.is_active = True
        self.user.is_removed = True
        self.assertEqual(resolve_ai_tier(self.user).name, "blocked")

    def test_staff_and_moderators_are_privileged(self):
        # Arrange / Act / Assert
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.assertEqual(resolve_ai_tier(self.user).name, "privileged")

        self.user.is_staff = False
        self.user.moderator = True
        self.user.save(update_fields=["is_staff", "moderator"])
        self.assertEqual(resolve_ai_tier(self.user).name, "privileged")

    def test_hub_editors_are_privileged(self):
        # Arrange
        editor, _hub = create_hub_editor("budget-editor", "Budget Editor Hub")

        # Act / Assert
        policy = resolve_ai_tier(editor)
        self.assertEqual(policy.name, "privileged")
        self.assertEqual(policy.daily_budget_microusd, 100_000_000)

    def test_registered_experts_receive_invited_tier(self):
        # Arrange
        Expert.objects.create(email="invitee@example.com", registered_user=self.user)

        # Act / Assert
        policy = resolve_ai_tier(self.user)
        self.assertEqual(policy.name, "invited")
        self.assertEqual(policy.daily_budget_microusd, 10_000_000)

    def test_privileged_role_precedes_invited_tier(self):
        # Arrange
        Expert.objects.create(email="staff@example.com", registered_user=self.user)
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])

        # Act / Assert
        self.assertEqual(resolve_ai_tier(self.user).name, "privileged")


@override_settings(OPENROUTER_API_KEY="or-test")
class UsageBudgetTests(TestCase):
    MODEL = "openrouter:deepseek/deepseek-v4-flash-0731"

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
        self.assertEqual(
            status.as_dict()["credits"],
            {"daily_limit": "250", "used": "1.65", "remaining": "248.35"},
        )

    def test_admission_raises_when_daily_turn_cap_is_spent(self):
        # Arrange
        LLMUsageEvent.objects.bulk_create(
            [
                LLMUsageEvent(
                    user=self.user,
                    feature="notebook_chat",
                    provider="openrouter",
                    model="deepseek/deepseek-v4-pro-0813",
                    cost_microusd=1,
                )
                for _ in range(10)
            ]
        )

        # Act / Assert
        with self.assertRaises(UsageLimitExceededError) as raised:
            check_turn_admission(
                self.user, self.MODEL, effort="none", thinking="disabled"
            )
        self.assertEqual(raised.exception.status.turns_used, 10)

    def test_default_tier_rejects_locked_model(self):
        with self.assertRaisesRegex(ValueError, "not allowed"):
            check_turn_admission(
                self.user,
                "claude_platform:claude-opus-5",
            )


@override_settings(OPENROUTER_API_KEY="or-test")
class AgentLoopBudgetRecorderTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("loop-budget")

    def test_records_provider_usage_without_double_counting_assistant_message(self):
        # Arrange
        recorder = AgentLoopBudgetRecorder(
            user=self.user,
            feature="notebook_chat",
            provider="openrouter",
            model_id="deepseek/deepseek-v4-pro-0813",
        )
        turn = AssistantTurn(
            text_blocks=[TextBlock(text="done")],
            tool_calls=[],
            stop_reason=StopReason.END_TURN,
            usage=TurnUsage(input_tokens=100, output_tokens=50),
        )

        # Act
        recorder.record_usage(turn.usage)
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="done")]),
            turn=turn,
        )

        # Assert
        event = LLMUsageEvent.objects.get()
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.feature, "notebook_chat")
        self.assertEqual(event.input_tokens, 100)
        self.assertEqual(LLMUsageEvent.objects.count(), 1)

    def test_pre_spend_guard_reloads_a_soft_deleted_user(self):
        # Arrange: keep the stale instance a running job would hold while a
        # separate request changes the authoritative database row.
        get_user_model().all_objects.filter(pk=self.user.pk).update(
            is_active=False,
            is_removed=True,
        )
        recorder = AgentLoopBudgetRecorder(
            user=self.user,
            feature="notebook_chat",
            provider="openrouter",
            model_id="deepseek/deepseek-v4-pro-0813",
        )

        # Act / Assert
        with self.assertRaisesMessage(BudgetExceededError, "access is blocked"):
            recorder.before_model_call()

    def _execution(self, *, status, expires_at):
        conversation = AgentConversation.objects.create(
            user=self.user,
            workflow="notebook_chat",
        )
        return AgentExecution.objects.create(
            conversation=conversation,
            status=status,
            attempt=1,
            usage_reservation_expires_at=expires_at,
        )

    def _recorder(self, execution):
        return AgentLoopBudgetRecorder(
            user=self.user,
            feature="notebook_chat",
            provider="openrouter",
            model_id="deepseek/deepseek-v4-pro-0813",
            execution=execution,
        )

    def test_before_model_call_renews_an_active_worker_lease(self):
        # Arrange
        old_expiry = timezone.now() + timedelta(minutes=1)
        execution = self._execution(
            status=AgentExecution.Status.RUNNING,
            expires_at=old_expiry,
        )

        # Act
        self._recorder(execution).before_model_call()

        # Assert
        execution.refresh_from_db()
        self.assertGreater(execution.usage_reservation_expires_at, old_expiry)

    def test_discarded_attempt_is_charged_before_retry_admission(self):
        # Arrange: nine earlier calls leave one turn in the default tier.
        LLMUsageEvent.objects.bulk_create(
            [
                LLMUsageEvent(
                    user=self.user,
                    feature="notebook_chat",
                    provider="openrouter",
                    model="deepseek/deepseek-v4-pro-0813",
                    cost_microusd=1,
                )
                for _ in range(9)
            ]
        )
        execution = self._execution(
            status=AgentExecution.Status.RUNNING,
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        recorder = self._recorder(execution)

        # Act: the completed first attempt consumes the last turn before the
        # provider asks whether it may make its internal retry.
        recorder.record_usage(TurnUsage(input_tokens=10, output_tokens=2))

        # Assert
        with self.assertRaises(BudgetExceededError):
            recorder.before_model_call()
        self.assertEqual(LLMUsageEvent.objects.filter(user=self.user).count(), 10)

    def test_stream_activity_renews_a_cancelled_in_flight_lease(self):
        # Arrange
        old_expiry = timezone.now() + timedelta(minutes=1)
        execution = self._execution(
            status=AgentExecution.Status.CANCELLED,
            expires_at=old_expiry,
        )

        # Act
        self._recorder(execution).record_stream_event(
            1, TextStreamDelta(block_index=0, text="still running")
        )

        # Assert
        execution.refresh_from_db()
        self.assertGreater(execution.usage_reservation_expires_at, old_expiry)

    def test_stream_activity_throttles_lease_renewals(self):
        # Arrange
        execution = self._execution(
            status=AgentExecution.Status.RUNNING,
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        recorder = self._recorder(execution)

        # Act
        with patch(
            "research_ai.services.usage_budget.recorder.renew_live_reservation"
        ) as renew:
            recorder.record_stream_event(
                1, TextStreamDelta(block_index=0, text="first event")
            )
            recorder.record_stream_event(
                1, TextStreamDelta(block_index=0, text="second event")
            )

        # Assert
        renew.assert_called_once()

    def test_expired_lease_cannot_be_resurrected_by_a_zombie_worker(self):
        # Arrange
        old_expiry = timezone.now() - timedelta(seconds=1)
        execution = self._execution(
            status=AgentExecution.Status.CANCELLED,
            expires_at=old_expiry,
        )

        # Act
        self._recorder(execution).record_stream_event(
            1, TextStreamDelta(block_index=0, text="late event")
        )

        # Assert
        execution.refresh_from_db()
        self.assertEqual(execution.usage_reservation_expires_at, old_expiry)

    def test_cancelled_owner_cannot_start_another_model_call(self):
        # Arrange
        execution = self._execution(
            status=AgentExecution.Status.CANCELLED,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        # Act / Assert
        with self.assertRaises(InterruptedError):
            self._recorder(execution).before_model_call()


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
                    conversation = AgentConversation.objects.create(
                        user=user,
                        workflow="notebook_chat",
                    )
                    AgentExecution.objects.create(
                        conversation=conversation,
                        status=AgentExecution.Status.PENDING,
                        attempt=1,
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

    def test_cancelled_call_blocks_admission_until_its_reservation_is_released(self):
        # Arrange: cancellation is visible immediately, but the provider call
        # that was already in flight has not returned to its worker yet.
        conversation = AgentConversation.objects.create(
            user=self.user,
            workflow="notebook_chat",
        )
        execution = AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.CANCELLED,
            attempt=1,
            usage_reservation_expires_at=timezone.now() + timedelta(hours=1),
        )

        # Act & Assert
        with (
            self.assertRaises(UsageWorkInProgressError),
            atomic_turn_admission(self.user),
        ):
            pass

        # The worker releases the separate reservation after the call returns.
        execution.usage_reservation_expires_at = None
        execution.save(update_fields=["usage_reservation_expires_at"])
        with atomic_turn_admission(self.user):
            pass

    def test_expired_cancelled_call_does_not_block_admission(self):
        # Arrange: the worker died and stopped renewing this lease.
        conversation = AgentConversation.objects.create(
            user=self.user,
            workflow="notebook_chat",
        )
        AgentExecution.objects.create(
            conversation=conversation,
            status=AgentExecution.Status.CANCELLED,
            attempt=1,
            usage_reservation_expires_at=timezone.now() - timedelta(seconds=1),
        )

        # Act / Assert
        with atomic_turn_admission(self.user):
            pass


class RequiredModelPricingTests(SimpleTestCase):
    def setUp(self):
        self.policy = TierPolicy("privileged", None, None, None, None)
        self.unpriced_model = "bedrock:us.anthropic.claude-opus-5"

    def test_unlimited_tier_cannot_submit_an_unpriced_model(self):
        # Arrange / Act / Assert
        with (
            patch.object(
                usage_budget_service, "resolve_ai_tier", return_value=self.policy
            ),
            self.assertRaisesMessage(ModelNotAllowedError, "no reviewed pricing"),
        ):
            check_turn_admission(object(), self.unpriced_model)

    @override_settings(RESEARCH_AI_GENERATOR_PROVIDER="bedrock")
    def test_unlimited_tier_default_falls_back_to_a_priced_model(self):
        # Arrange / Act
        default = usage_budget_service.resolve_default_model(self.policy)

        # Assert
        self.assertEqual(default, "claude_platform:claude-opus-5")

    def test_no_priced_model_prevents_default_selection(self):
        # Arrange / Act / Assert
        with (
            patch.object(
                usage_budget_service,
                "available_models",
                return_value=[ModelOption(self.unpriced_model, "Unpriced")],
            ),
            self.assertRaisesMessage(ModelNotAllowedError, "No configured model"),
        ):
            usage_budget_service.resolve_default_model(self.policy)

    def test_unpriced_execution_is_stopped_before_provider_call(self):
        # Arrange: no user or admission check is needed to enforce pricing.
        provider = FakeProvider([_build_text_turn("Must not run")])
        recorder = AgentLoopBudgetRecorder(
            user=None,
            feature="notebook_chat",
            provider="bedrock",
            model_id="us.anthropic.claude-opus-5",
        )
        agent = AgentService(provider=provider, max_iterations=None).create_agent(
            Toolset([]), system_prompt="Test", recorder=recorder
        )

        # Act
        with self.assertRaisesMessage(ProviderError, "no reviewed pricing") as raised:
            agent.run("Hello")

        # Assert
        self.assertEqual(provider.calls, [])
        self.assertFalse(raised.exception.retryable)


class CreditBudgetStatusTests(SimpleTestCase):
    def test_credit_meter_preserves_unlimited_and_exhausted_budgets(self):
        # Arrange
        cases = [
            (None, None, None),
            (250_000, "250", "0"),
        ]

        # Act / Assert
        for budget, limit, remaining in cases:
            with self.subTest(budget=budget):
                meter = BudgetStatus(
                    tier="default",
                    daily_budget_microusd=budget,
                    spent_today_microusd=300_001,
                    turns_used=12,
                    turn_cap=None,
                    resets_at=datetime(2026, 9, 5, tzinfo=UTC),
                ).as_dict()["credits"]
                self.assertEqual(
                    meter,
                    {"daily_limit": limit, "used": "300.001", "remaining": remaining},
                )


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
                "credits",
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
        self.assertEqual(
            response.json()["credits"],
            {"daily_limit": "250", "used": "0", "remaining": "250"},
        )
