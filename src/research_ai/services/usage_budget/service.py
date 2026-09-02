"""Tier resolution, accounting, and admission for Research AI spend."""

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import BigIntegerField, Count, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from research_ai.models import (
    AgentExecution,
    LLMUsageEvent,
    ProposalDraft,
)
from research_ai.services.agent.errors import BudgetExceededError
from research_ai.services.agent.model_capabilities import EFFORT_LEVELS
from research_ai.services.agent.model_pricing import cost_microusd, model_pricing
from research_ai.services.agent.providers.registry import split_model_ref
from research_ai.services.agent.types import TurnUsage
from research_ai.services.usage_budget.config import TierPolicy, tier_policies


class ModelNotAllowedError(ValueError):
    code = "model_not_allowed"


class UsageLimitExceededError(RuntimeError):
    code = "usage_limit_exceeded"

    def __init__(self, status: "BudgetStatus"):
        super().__init__("Daily Research AI usage limit exceeded")
        self.status = status


class UsageWorkInProgressError(RuntimeError):
    code = "usage_work_in_progress"


@dataclass(frozen=True)
class BudgetStatus:
    tier: str
    daily_budget_microusd: int | None
    spent_today_microusd: int
    turns_used: int
    turn_cap: int | None
    resets_at: datetime

    @property
    def remaining_microusd(self) -> int | None:
        if self.daily_budget_microusd is None:
            return None
        return max(0, self.daily_budget_microusd - self.spent_today_microusd)

    @property
    def exhausted(self) -> bool:
        budget_hit = (
            self.daily_budget_microusd is not None
            and self.spent_today_microusd >= self.daily_budget_microusd
        )
        cap_hit = self.turn_cap is not None and self.turns_used >= self.turn_cap
        return budget_hit or cap_hit

    @staticmethod
    def _usd(value: int | None) -> str | None:
        if value is None:
            return None
        return format(Decimal(value) / Decimal(1000000), "f")

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "daily_budget": self._usd(self.daily_budget_microusd),
            "spent_today": self._usd(self.spent_today_microusd),
            "remaining": self._usd(self.remaining_microusd),
            "turns_used": self.turns_used,
            "turn_cap": self.turn_cap,
            "resets_at": self.resets_at.isoformat().replace("+00:00", "Z"),
        }


def resolve_ai_tier(user) -> TierPolicy:
    policies = tier_policies()
    if (
        user is None
        or not getattr(user, "is_authenticated", False)
        or getattr(user, "is_suspended", False)
        or getattr(user, "probable_spammer", False)
    ):
        return policies["blocked"]
    if getattr(user, "is_staff", False) or getattr(user, "moderator", False):
        return policies["privileged"]
    return policies["default"]


def _utc_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or timezone.now()
    utc_now = now.astimezone(UTC)
    start = datetime.combine(utc_now.date(), time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def budget_status(user, *, now: datetime | None = None) -> BudgetStatus:
    policy = resolve_ai_tier(user)
    start, reset = _utc_window(now)
    usage = LLMUsageEvent.objects.filter(
        user=user, created_date__gte=start, created_date__lt=reset
    ).aggregate(
        spent=Coalesce(Sum("cost_microusd"), 0, output_field=BigIntegerField()),
        turns=Count("id"),
    )
    return BudgetStatus(
        tier=policy.name,
        daily_budget_microusd=policy.daily_budget_microusd,
        spent_today_microusd=int(usage["spent"] or 0),
        turns_used=int(usage["turns"] or 0),
        turn_cap=policy.daily_turn_cap,
        resets_at=reset,
    )


def _validate_model(policy: TierPolicy, model_ref: str) -> None:
    if policy.name == "blocked":
        raise ModelNotAllowedError("Research AI access is blocked")
    if (
        policy.allowed_model_refs is not None
        and model_ref not in policy.allowed_model_refs
    ):
        raise ModelNotAllowedError(
            f"model {model_ref!r} is not allowed for tier {policy.name!r}"
        )
    provider, model_id = split_model_ref(model_ref)
    if policy.is_budgeted and model_pricing(provider, model_id or "") is None:
        raise ModelNotAllowedError(f"model {model_ref!r} has no reviewed pricing")


def effective_generation_options(
    policy: TierPolicy,
    *,
    effort: str | None,
    thinking: str | None,
) -> tuple[str | None, str | None]:
    """Apply tier defaults and reject controls above its ceiling."""
    if policy.max_effort is not None:
        maximum = EFFORT_LEVELS.index(policy.max_effort)
        effective_effort = effort if effort is not None else policy.max_effort
        if (
            effective_effort not in EFFORT_LEVELS
            or EFFORT_LEVELS.index(effective_effort) > maximum
        ):
            raise ModelNotAllowedError(
                f"effort {effective_effort!r} is not allowed for tier {policy.name!r}"
            )
        effort = effective_effort
    if policy.allowed_thinking_modes is not None:
        thinking = (
            thinking if thinking is not None else policy.allowed_thinking_modes[0]
        )
        if thinking not in policy.allowed_thinking_modes:
            raise ModelNotAllowedError(
                f"thinking {thinking!r} is not allowed for tier {policy.name!r}"
            )
    return effort, thinking


def check_turn_admission(
    user,
    model_ref: str,
    *,
    effort: str | None = None,
    thinking: str | None = None,
) -> BudgetStatus:
    policy = resolve_ai_tier(user)
    _validate_model(policy, model_ref)
    effective_generation_options(policy, effort=effort, thinking=thinking)
    status = budget_status(user)
    if getattr(settings, "RESEARCH_AI_BUDGETS_ENFORCED", True) and status.exhausted:
        raise UsageLimitExceededError(status)
    return status


def check_budget_admission(user) -> BudgetStatus:
    """Check only the dollar/turn counters for a fixed-model feature."""
    status = budget_status(user)
    if getattr(settings, "RESEARCH_AI_BUDGETS_ENFORCED", True) and status.exhausted:
        raise UsageLimitExceededError(status)
    return status


def _has_in_flight_work(user) -> bool:
    """Whether a budgeted user already has spend-producing work reserved."""
    return (
        AgentExecution.objects.filter(
            conversation__user=user,
            status__in=[
                AgentExecution.Status.PENDING,
                AgentExecution.Status.RUNNING,
            ],
        ).exists()
        or ProposalDraft.objects.filter(
            created_by=user,
            status__in=[
                ProposalDraft.Status.PENDING,
                ProposalDraft.Status.PROCESSING,
            ],
        ).exists()
    )


@contextmanager
def atomic_turn_admission(
    user,
    model_ref: str | None = None,
    *,
    effort: str | None = None,
    thinking: str | None = None,
):
    """Atomically reserve one in-flight budgeted job for ``user``.

    The caller must create its pending execution or draft before leaving
    this context. That row is the reservation observed by the next admission.
    Restricting budgeted users to one in-flight top-level job keeps soft
    enforcement's overshoot bounded to the currently running provider call.
    """
    with transaction.atomic():
        locked_user = type(user)._default_manager.select_for_update().get(pk=user.pk)
        policy = resolve_ai_tier(locked_user)
        enforced = getattr(settings, "RESEARCH_AI_BUDGETS_ENFORCED", True)
        if enforced and policy.is_budgeted and _has_in_flight_work(locked_user):
            raise UsageWorkInProgressError(
                "Another Research AI request is still in progress"
            )
        status = (
            check_turn_admission(
                locked_user,
                model_ref,
                effort=effort,
                thinking=thinking,
            )
            if model_ref is not None
            else check_budget_admission(locked_user)
        )
        yield status


def record(
    user,
    feature: str,
    provider: str,
    model_id: str,
    usage: TurnUsage,
    *,
    execution=None,
) -> LLMUsageEvent:
    return LLMUsageEvent.objects.create(
        user=user,
        feature=feature,
        provider=provider,
        model=model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_microusd=cost_microusd(provider, model_id, usage),
        execution=execution,
    )


def ensure_budget_available(user) -> None:
    """Between-iteration guard used by database-backed agent recorders."""
    policy = resolve_ai_tier(user)
    if not policy.is_budgeted or not getattr(
        settings, "RESEARCH_AI_BUDGETS_ENFORCED", True
    ):
        return
    status = budget_status(user)
    if status.exhausted:
        raise BudgetExceededError("Daily Research AI usage limit exceeded")
