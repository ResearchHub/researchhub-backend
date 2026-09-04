"""Budget accounting wrapper for calls made by the modern agent loop."""

import logging

from django.utils import timezone

from research_ai.services.agent.errors import ProviderError
from research_ai.services.agent.model_pricing import model_pricing
from research_ai.services.agent.types import AssistantTurn, Message, TurnUsage
from research_ai.services.usage_budget.reservation import (
    USAGE_RESERVATION_RENEW_INTERVAL,
    renew_active_reservation,
    renew_live_reservation,
)
from research_ai.services.usage_budget.service import (
    ensure_budget_available,
    record,
    record_call_start,
    settle_call,
)

logger = logging.getLogger(__name__)


class AgentLoopBudgetRecorder:
    """Add per-call budget checks and accounting to an optional loop recorder.

    The wrapper is deliberately attached at ``AgentService`` call sites. Direct
    provider integrations and legacy LLM workflows never receive it and remain
    outside this budget rollout.
    """

    def __init__(
        self,
        *,
        user,
        feature: str,
        provider: str,
        model_id: str,
        recorder=None,
        execution=None,
        reservation_targets=None,
    ):
        self.user = user
        self.feature = feature
        self.provider = provider
        self.model_id = model_id
        self._recorder = recorder
        self.execution = execution or getattr(recorder, "execution", None)
        targets = (
            reservation_targets
            if reservation_targets is not None
            else (self.execution,)
        )
        self._reservation_targets = tuple(target for target in targets if target)
        self._next_reservation_renewal_at = None
        self._pending_usage_event = None
        # Losing a usage row would silently reopen budget that was actually
        # spent, so accounting writes are required even without a transcript.
        self.requires_durable_usage = True

    def __getattr__(self, name):
        if self._recorder is None:
            raise AttributeError(name)
        return getattr(self._recorder, name)

    def is_active(self) -> bool:
        callback = getattr(self._recorder, "is_active", None)
        return True if callback is None else callback()

    def before_model_call(self) -> None:
        # Recheck queued/pinned models and fixed-model nested agents at the
        # point of spend, even if admission happened before a pricing change.
        if model_pricing(self.provider, self.model_id) is None:
            raise ProviderError(
                f"model {self.provider}:{self.model_id} has no reviewed pricing",
                retryable=False,
            )
        if self.user is not None:
            ensure_budget_available(self.user)
        now = timezone.now()
        for target in self._reservation_targets:
            if not renew_active_reservation(target, now=now):
                raise InterruptedError("usage reservation owner is no longer active")
        self._next_reservation_renewal_at = now + USAGE_RESERVATION_RENEW_INTERVAL
        callback = getattr(self._recorder, "before_model_call", None)
        if callback is not None:
            callback()
        if self.user is not None:
            self._pending_usage_event = record_call_start(
                self.user,
                self.feature,
                self.provider,
                self.model_id,
                execution=self.execution,
            )

    def record_usage(self, usage: TurnUsage) -> None:
        if self.user is not None:
            if self._pending_usage_event is None:
                record(
                    self.user,
                    self.feature,
                    self.provider,
                    self.model_id,
                    usage,
                    execution=self.execution,
                )
            else:
                settle_call(self._pending_usage_event, usage)
                self._pending_usage_event = None
        callback = getattr(self._recorder, "record_usage", None)
        if callback is not None:
            callback(usage)

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        if self._recorder is not None:
            self._recorder.record_message(message, turn=turn)

    def on_run_finished(self, result):
        callback = getattr(self._recorder, "on_run_finished", None)
        return None if callback is None else callback(result)

    def on_run_failed(self, error: Exception):
        callback = getattr(self._recorder, "on_run_failed", None)
        return None if callback is None else callback(error)

    def record_stream_event(self, iteration, event) -> None:
        now = timezone.now()
        if (
            self._next_reservation_renewal_at is None
            or now >= self._next_reservation_renewal_at
        ):
            for target in self._reservation_targets:
                try:
                    renew_live_reservation(target, now=now)
                except Exception:  # noqa: BLE001 - lease refresh cannot break a turn
                    logger.warning(
                        "could not renew usage reservation from stream activity",
                        extra={
                            "target_type": type(target).__name__,
                            "target_id": target.id,
                        },
                        exc_info=True,
                    )
            self._next_reservation_renewal_at = now + USAGE_RESERVATION_RENEW_INTERVAL
        callback = getattr(self._recorder, "record_stream_event", None)
        if callback is not None:
            callback(iteration, event)

    def flush_stream_events(self) -> None:
        callback = getattr(self._recorder, "flush_stream_events", None)
        if callback is not None:
            callback()
