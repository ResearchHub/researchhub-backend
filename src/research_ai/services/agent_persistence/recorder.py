"""Database-backed observational recorder for one agent execution."""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from research_ai.models import (
    AgentContextMessage,
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.agent.errors import IterationLimitError
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    ToolResultBlock,
)
from research_ai.services.agent_persistence.content import (
    bounded_payload,
    serialize_context_message,
    serialize_final_output,
    serialize_trace_message,
)
from research_ai.services.agent_persistence.replacement import (
    replaced_execution_ids,
    superseded_execution_ids,
)

logger = logging.getLogger(__name__)

_MAX_ERROR_CHARS = 10_000


def _add_optional(current: int | None, increment: int | None) -> int | None:
    if increment is None:
        return current
    return (current or 0) + increment


def _duration_ms(started_at, finished_at) -> int | None:
    if started_at is None:
        return None
    elapsed: timedelta = finished_at - started_at
    return max(0, round(elapsed.total_seconds() * 1000))


def _safe_exception_message(error: object) -> str:
    try:
        return str(error)[:_MAX_ERROR_CHARS]
    except Exception:  # noqa: BLE001 - terminal persistence must remain defensive
        return f"<{type(error).__name__} message unavailable>"


def _is_terminal(status: str) -> bool:
    return status not in {
        AgentExecution.Status.PENDING,
        AgentExecution.Status.RUNNING,
    }


def _turn_trace_fields(turn: AssistantTurn | None) -> dict:
    usage = turn.usage if turn else None
    return {
        "provider_stop_reason": turn.stop_reason.value if turn else "",
        "input_tokens": usage.input_tokens if usage else None,
        "output_tokens": usage.output_tokens if usage else None,
        "cache_read_tokens": usage.cache_read_tokens if usage else None,
        "cache_write_tokens": usage.cache_write_tokens if usage else None,
        "latency_ms": turn.latency_ms if turn else None,
    }


def _apply_turn_metrics(
    execution: AgentExecution,
    turn: AssistantTurn | None,
    trace_fields: dict,
) -> list[str]:
    if turn is None:
        return []
    execution.iterations += 1
    execution.stop_reason = turn.stop_reason.value
    execution.input_tokens = _add_optional(
        execution.input_tokens, trace_fields["input_tokens"]
    )
    execution.output_tokens = _add_optional(
        execution.output_tokens, trace_fields["output_tokens"]
    )
    execution.cache_read_tokens = _add_optional(
        execution.cache_read_tokens, trace_fields["cache_read_tokens"]
    )
    execution.cache_write_tokens = _add_optional(
        execution.cache_write_tokens, trace_fields["cache_write_tokens"]
    )
    execution.total_latency_ms = _add_optional(
        execution.total_latency_ms, turn.latency_ms
    )
    return [
        "iterations",
        "stop_reason",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "total_latency_ms",
    ]


class DatabaseAgentRecorder:
    """Persist required context and isolate optional observational trace writes.

    Callers must drive the agent outside their own ``transaction.atomic()``
    block. Django nests ``atomic()`` as a savepoint, so an outer rollback would
    discard the context rows and the terminal status transition together, and an
    execution created before that transaction would stay ``RUNNING`` and block
    every later execution on the conversation.
    """

    requires_durable_messages = True

    def __init__(
        self,
        execution: AgentExecution,
        *,
        initial_prompt_provenance: str = AgentExecutionMessage.Provenance.BACKEND,
        publish_assistant_message: bool | None = None,
    ):
        self.execution = execution
        self.initial_prompt_provenance = initial_prompt_provenance
        self.publish_assistant_message = (
            execution.publish_output_to_chat
            if publish_assistant_message is None
            else publish_assistant_message
        )
        self._recorded_messages = 0
        self.terminal_observed = False

    def set_system_prompt(self, system_prompt: str) -> None:
        """Snapshot model-only scaffolding after callers finish composing it."""
        with transaction.atomic():
            AgentExecution.objects.filter(id=self.execution.id).update(
                system_prompt=system_prompt,
                last_activity_at=timezone.now(),
            )

    def is_active(self) -> bool:
        """Whether this execution is still ours to advance.

        The agent loop calls this before each tool call so a run cancelled or
        reclaimed elsewhere stops before the tool takes effect. One indexed read
        per tool call, against a model turn that costs seconds at minimum.
        """
        return AgentExecution.objects.filter(
            id=self.execution.id,
            status__in=[
                AgentExecution.Status.PENDING,
                AgentExecution.Status.RUNNING,
            ],
        ).exists()

    def _provenance(self, message: Message) -> str:
        if message.role == "assistant":
            return AgentExecutionMessage.Provenance.MODEL
        if any(isinstance(block, ToolResultBlock) for block in message.content):
            return AgentExecutionMessage.Provenance.TOOL
        if self._recorded_messages == 0:
            return self.initial_prompt_provenance
        return AgentExecutionMessage.Provenance.BACKEND

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        context_content, context_provider_state, is_compacted, context_original_size = (
            serialize_context_message(message)
        )
        now = timezone.now()
        provenance = self._provenance(message)

        # Resumable context is durable state, not disposable debugging data, so
        # it gets its own atomic block: the trace write that follows rolls back
        # to its own savepoint instead of erasing the context a later turn
        # needs. That isolates it from the trace write, not from a caller's
        # transaction -- see the class docstring.
        with transaction.atomic():
            execution = AgentExecution.objects.select_for_update().get(
                id=self.execution.id
            )
            # A cancellation from another process ends this run's claim on its
            # own context. Continuing to append would land after the seal a
            # later turn wrote to close this run's open tool calls, leaving two
            # results for one call in a lineage providers reject on replay.
            if _is_terminal(execution.status):
                raise InterruptedError("agent execution is no longer running")
            AgentContextMessage.objects.create(
                execution=execution,
                sequence=execution.next_context_sequence,
                role=message.role,
                content=context_content,
                provider_state=context_provider_state,
                is_compacted=is_compacted,
                original_size_bytes=(context_original_size if is_compacted else None),
            )
            execution.next_context_sequence += 1
            execution.last_activity_at = now
            execution.save(
                update_fields=[
                    "next_context_sequence",
                    "last_activity_at",
                    "updated_date",
                ]
            )
        self._recorded_messages += 1

        try:
            content, is_truncated, original_size = serialize_trace_message(message)
            self._record_trace(
                message=message,
                turn=turn,
                content=content,
                is_truncated=is_truncated,
                original_size=original_size,
                now=now,
                provenance=provenance,
            )
        except Exception:  # noqa: BLE001 - trace data is optional observability
            logger.warning("failed to persist optional agent trace", exc_info=True)

    def _record_trace(
        self,
        *,
        message: Message,
        turn: AssistantTurn | None,
        content: list[dict],
        is_truncated: bool,
        original_size: int,
        now,
        provenance: str,
    ) -> None:
        # The nested atomic block is intentional: if this write raises inside a
        # caller's transaction, Django rolls back this savepoint before this
        # optional trace failure is swallowed, leaving the outer transaction usable.
        with transaction.atomic():
            conversation = AgentConversation.objects.select_for_update().get(
                id=self.execution.conversation_id
            )
            execution = AgentExecution.objects.select_for_update().get(
                id=self.execution.id
            )
            global_sequence = conversation.next_trace_sequence
            execution_sequence = execution.next_message_sequence

            turn_fields = _turn_trace_fields(turn)
            AgentExecutionMessage.objects.create(
                conversation=conversation,
                execution=execution,
                sequence=global_sequence,
                execution_sequence=execution_sequence,
                role=message.role,
                provenance=provenance,
                content=content,
                is_truncated=is_truncated,
                original_size_bytes=original_size if is_truncated else None,
                **turn_fields,
            )

            conversation.next_trace_sequence += 1
            conversation.save(update_fields=["next_trace_sequence", "updated_date"])

            execution.next_message_sequence += 1
            execution.last_activity_at = now
            update_fields = [
                "next_message_sequence",
                "last_activity_at",
                "updated_date",
            ]
            update_fields.extend(_apply_turn_metrics(execution, turn, turn_fields))
            execution.save(update_fields=update_fields)

    def on_run_finished(self, result) -> None:
        now = timezone.now()
        final_output, _truncated, _size = serialize_final_output(result.final_text)
        transitioned = False
        with transaction.atomic():
            execution = AgentExecution.objects.select_for_update().get(
                id=self.execution.id
            )
            if execution.status == AgentExecution.Status.RUNNING:
                execution.status = AgentExecution.Status.SUCCEEDED
                execution.final_output = final_output
                execution.stop_reason = result.stop_reason
                execution.iterations = max(execution.iterations, result.iterations)
                execution.finished_at = now
                execution.last_activity_at = now
                execution.duration_ms = _duration_ms(execution.started_at, now)
                execution.save(
                    update_fields=[
                        "status",
                        "final_output",
                        "stop_reason",
                        "iterations",
                        "finished_at",
                        "last_activity_at",
                        "duration_ms",
                        "updated_date",
                    ]
                )
                transitioned = True
            terminal = _is_terminal(execution.status)
        self.terminal_observed = terminal
        if not transitioned:
            return
        # Publish what the model actually answered, not the snapshot trimmed to
        # fit the execution row: chat content is unbounded text, so truncating
        # it here would drop the tail of a successful response for good.
        if self.publish_assistant_message and result.final_text:
            try:
                self.publish_assistant_output(result.final_text)
            except Exception:  # noqa: BLE001 - trace terminal state already landed
                logger.warning(
                    "failed to publish agent response to chat", exc_info=True
                )

    def on_run_failed(self, error: Exception) -> None:
        now = timezone.now()
        raw_stop_reason = getattr(error, "stop_reason", "") or ""
        stop_reason = _safe_exception_message(raw_stop_reason)
        if not stop_reason:
            if isinstance(error, InterruptedError):
                stop_reason = "interrupted"
            elif isinstance(error, IterationLimitError):
                stop_reason = "iteration_limit"
            else:
                stop_reason = "error"
        cause = getattr(error, "__cause__", None)
        details = {
            "stop_reason": stop_reason,
            "iterations": getattr(error, "iterations", None),
            "cause_type": type(cause).__name__ if cause else None,
            "cause_message": _safe_exception_message(cause) if cause else None,
        }
        safe_details, _truncated, _size = bounded_payload(details)
        status = (
            AgentExecution.Status.INTERRUPTED
            if isinstance(error, InterruptedError)
            else AgentExecution.Status.FAILED
        )
        with transaction.atomic():
            execution = AgentExecution.objects.select_for_update().get(
                id=self.execution.id
            )
            if execution.status == AgentExecution.Status.RUNNING:
                execution.status = status
                execution.error_type = type(error).__name__
                execution.error_message = _safe_exception_message(error)
                execution.error_details = safe_details
                execution.stop_reason = stop_reason
                error_iterations = getattr(error, "iterations", None)
                if error_iterations is not None:
                    execution.iterations = max(execution.iterations, error_iterations)
                execution.finished_at = now
                execution.last_activity_at = now
                execution.duration_ms = _duration_ms(execution.started_at, now)
                execution.save(
                    update_fields=[
                        "status",
                        "error_type",
                        "error_message",
                        "error_details",
                        "stop_reason",
                        "iterations",
                        "finished_at",
                        "last_activity_at",
                        "duration_ms",
                        "updated_date",
                    ]
                )
            terminal = _is_terminal(execution.status)
        self.terminal_observed = terminal

    def publish_assistant_output(self, text: str | None = None) -> bool:
        """Publish or repair the canonical assistant message idempotently."""
        with transaction.atomic():
            conversation = AgentConversation.objects.select_for_update().get(
                id=self.execution.conversation_id
            )
            execution = AgentExecution.objects.select_for_update().get(
                id=self.execution.id
            )
            if (
                execution.status != AgentExecution.Status.SUCCEEDED
                or not execution.publish_output_to_chat
            ):
                return False
            if text is None:
                final_output = execution.final_output
                text = (
                    final_output.get("text") if isinstance(final_output, dict) else None
                )
            if not isinstance(text, str) or not text:
                return False
            # Re-read supersession here rather than trusting the caller's scan.
            # A regeneration that publishes between that scan and this lock
            # finds no ancestor message to deactivate, so nothing but this
            # check stops the answer it replaced from landing behind it.
            if execution.id in superseded_execution_ids(conversation):
                return False
            if execution.replaces_output_of_id:
                AgentConversationMessage.objects.filter(
                    generated_by_execution_id__in=replaced_execution_ids(execution)
                ).update(is_active=False)
            _message, created = AgentConversationMessage.objects.get_or_create(
                generated_by_execution_id=execution.id,
                defaults={
                    "conversation": conversation,
                    "sequence": conversation.next_chat_sequence,
                    "role": AgentConversationMessage.Role.ASSISTANT,
                    "content": text,
                    "in_reply_to_id": execution.trigger_message_id,
                },
            )
            if created:
                conversation.next_chat_sequence += 1
                conversation.save(update_fields=["next_chat_sequence", "updated_date"])
            return created
