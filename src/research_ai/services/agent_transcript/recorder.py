"""Database implementation of the neutral agent recorder protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from research_ai.models import AgentConversation, AgentMessage, AgentRun
from research_ai.services.agent.errors import (
    AgentRunError,
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.types import AssistantTurn, Message, serialize_messages

if TYPE_CHECKING:
    from research_ai.services.agent.loop import AgentResult

_DEFAULT_STRING_LIMIT = 100_000


class DatabaseAgentRecorder:
    """Persist agent messages incrementally into ``Agent*`` tables."""

    def __init__(
        self,
        conversation: AgentConversation,
        config: dict | None = None,
        *,
        model_id: str = "",
        max_string_chars: int | None = None,
    ):
        self.conversation = conversation
        self.config = dict(config or {})
        self.max_string_chars = (
            max_string_chars
            if max_string_chars is not None
            else getattr(
                settings,
                "RESEARCH_AI_AGENT_TRANSCRIPT_STRING_LIMIT",
                _DEFAULT_STRING_LIMIT,
            )
        )
        self._next_sequence = self._load_next_sequence()
        self.run = AgentRun.objects.create(
            conversation=conversation,
            model_id=model_id or self.config.get("model_id", ""),
            config=self.config,
        )

    def record_message(
        self,
        message: Message,
        *,
        turn: AssistantTurn | None = None,
    ) -> None:
        serialized = serialize_messages([message])[0]
        AgentMessage.objects.create(
            conversation=self.conversation,
            run=self.run,
            sequence=self._next_sequence,
            role=serialized["role"],
            content=[
                _truncate_block(block, self.max_string_chars)
                for block in serialized["content"]
            ],
            **self._turn_metadata(turn),
        )
        self._next_sequence += 1
        self._fold_usage(turn)

    def on_run_finished(self, result: AgentResult) -> None:
        self._finish(
            status=AgentRun.Status.COMPLETED,
            stop_reason=result.stop_reason,
            iterations=result.iterations,
        )

    def on_run_failed(self, error: AgentRunError) -> None:
        self._finish(
            status=AgentRun.Status.FAILED,
            stop_reason=_error_stop_reason(error),
            iterations=error.iterations or 0,
            error_message=str(error),
        )

    def _load_next_sequence(self) -> int:
        latest = AgentMessage.objects.filter(conversation=self.conversation).aggregate(
            sequence=Max("sequence")
        )["sequence"]
        return (latest or 0) + 1

    def _turn_metadata(self, turn: AssistantTurn | None) -> dict:
        if turn is None:
            return {}
        usage = turn.usage
        return {
            "input_tokens": usage.input_tokens if usage else None,
            "output_tokens": usage.output_tokens if usage else None,
            "cache_read_tokens": usage.cache_read_tokens if usage else None,
            "cache_write_tokens": usage.cache_write_tokens if usage else None,
            "latency_ms": turn.latency_ms,
            "stop_reason": turn.stop_reason.value,
        }

    def _fold_usage(self, turn: AssistantTurn | None) -> None:
        if turn is None or turn.usage is None:
            return
        usage = turn.usage
        self.run.input_tokens += usage.input_tokens
        self.run.output_tokens += usage.output_tokens
        self.run.cache_read_tokens += usage.cache_read_tokens
        self.run.cache_write_tokens += usage.cache_write_tokens
        self.run.save(
            update_fields=[
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "updated_date",
            ]
        )

    def _finish(
        self,
        *,
        status: str,
        stop_reason: str,
        iterations: int,
        error_message: str = "",
    ) -> None:
        now = timezone.now()
        self.run.status = status
        self.run.stop_reason = stop_reason
        self.run.iterations = iterations
        self.run.error_message = error_message
        self.run.finished_at = now
        self.run.duration = now - self.run.created_date
        self.run.save(
            update_fields=[
                "status",
                "stop_reason",
                "iterations",
                "error_message",
                "finished_at",
                "duration",
                "updated_date",
            ]
        )


def _error_stop_reason(error: AgentRunError) -> str:
    if isinstance(error, IncompleteTurnError):
        return error.stop_reason
    if isinstance(error, IterationLimitError):
        return "iteration_limit"
    if isinstance(error, ProviderError):
        return "provider_error"
    return "error"


def _truncate_block(block: dict, limit: int) -> dict:
    value, truncated = _truncate_value(block, limit)
    if truncated and isinstance(value, dict):
        value["truncated"] = True
    return value


def _truncate_value(value: Any, limit: int) -> tuple[Any, bool]:
    if isinstance(value, str):
        return (value[:limit], True) if len(value) > limit else (value, False)
    if isinstance(value, list):
        truncated = False
        values = []
        for item in value:
            item_value, item_truncated = _truncate_value(item, limit)
            values.append(item_value)
            truncated = truncated or item_truncated
        return values, truncated
    if isinstance(value, dict):
        truncated = False
        values = {}
        for key, item in value.items():
            item_value, item_truncated = _truncate_value(item, limit)
            values[key] = item_value
            truncated = truncated or item_truncated
        if truncated:
            values["truncated"] = True
        return values, truncated
    return value, False
