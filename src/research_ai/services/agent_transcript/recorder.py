"""The database implementation of the agent core's ``AgentRecorder`` protocol.

Writes are incremental -- a row per message as the loop appends it -- so the
transcript gives a live trace while a run is in progress, survives a hard
crash mid-run, and makes stuck runs inspectable. Message rows are insert-only:
the recorder never updates or deletes one after writing it; the mutable state
of a run lives on ``AgentRun``.

The loop swallows recorder exceptions (a transcript is observability; it must
not kill a run), so a persistence failure here costs rows, never the run.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from research_ai.models import AgentConversation, AgentMessage, AgentRun
from research_ai.services.agent import (
    AgentResult,
    AssistantTurn,
    Message,
    serialize_messages,
)

logger = logging.getLogger(__name__)

# Write-time safeguard: cap any single string inside a stored block so a
# pathological tool result (e.g. full PDF text) cannot produce an absurd row.
# Generous on purpose -- everything under the cap is stored verbatim.
_DEFAULT_MAX_BLOCK_CHARS = 100_000


def _cap_strings(value, limit: int):
    """Return ``value`` with every nested string capped, and whether any was."""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit], True
        return value, False
    if isinstance(value, dict):
        capped, truncated = {}, False
        for key, item in value.items():
            capped[key], hit = _cap_strings(item, limit)
            truncated = truncated or hit
        return capped, truncated
    if isinstance(value, list):
        capped, truncated = [], False
        for item in value:
            item, hit = _cap_strings(item, limit)
            capped.append(item)
            truncated = truncated or hit
        return capped, truncated
    return value, False


class DatabaseAgentRecorder:
    """Persists one agent run's transcript onto a conversation.

    Creates the ``AgentRun`` row on construction, appends an ``AgentMessage``
    row per recorded message (resuming the conversation's sequence counter, so
    a ``continue_conversation`` run keeps appending to the same log), folds
    each assistant turn's usage into the run aggregates as it lands, and
    finalizes the run row on finish or fail.
    """

    def __init__(
        self,
        conversation: AgentConversation,
        *,
        model_id: str = "",
        config: dict | None = None,
        max_block_chars: int | None = None,
    ):
        self.conversation = conversation
        self.max_block_chars = (
            max_block_chars
            if max_block_chars is not None
            else getattr(
                settings,
                "RESEARCH_AI_TRANSCRIPT_MAX_BLOCK_CHARS",
                _DEFAULT_MAX_BLOCK_CHARS,
            )
        )
        self.run = AgentRun.objects.create(
            conversation=conversation,
            status=AgentRun.Status.RUNNING,
            model_id=model_id,
            config=config or {},
        )

    # -- AgentRecorder protocol -------------------------------------------

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        content = serialize_messages([message])[0]["content"]
        content = [self._cap_block(block) for block in content]
        with transaction.atomic():
            # Conversations may have multiple overlapping runs. Lock the
            # shared parent while allocating the next sequence so two
            # recorders cannot claim the same position.
            AgentConversation.objects.select_for_update().only("pk").get(
                pk=self.conversation.pk
            )
            last_sequence = (
                AgentMessage.objects.filter(conversation=self.conversation)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
            )
            sequence = 0 if last_sequence is None else last_sequence + 1
            AgentMessage.objects.create(
                conversation=self.conversation,
                run=self.run,
                sequence=sequence,
                role=message.role,
                content=content,
                **self._turn_columns(turn),
            )
            if turn is not None:
                self._fold_turn_into_run(turn)

    def on_run_finished(self, result: AgentResult) -> None:
        self._finalize(
            status=AgentRun.Status.COMPLETED,
            stop_reason=result.stop_reason,
            iterations=result.iterations,
        )

    def on_run_failed(self, error: Exception) -> None:
        self._finalize(
            status=AgentRun.Status.FAILED,
            # Typed agent failures may carry a stop reason and iteration
            # count; unexpected failures retain the aggregates recorded so far.
            stop_reason=getattr(error, "stop_reason", "") or "",
            iterations=getattr(error, "iterations", None),
            error_message=str(error),
        )

    # -- private helpers ----------------------------------------------------

    def _cap_block(self, block: dict) -> dict:
        capped, truncated = _cap_strings(block, self.max_block_chars)
        if truncated:
            capped["truncated"] = True
        return capped

    def _turn_columns(self, turn: AssistantTurn | None) -> dict:
        """Per-turn metadata columns for an assistant row; empty otherwise."""
        if turn is None:
            return {}
        columns = {
            "latency_ms": turn.latency_ms,
            "stop_reason": turn.stop_reason.value,
        }
        if turn.usage is not None:
            columns.update(
                input_tokens=turn.usage.input_tokens,
                output_tokens=turn.usage.output_tokens,
                cache_read_tokens=turn.usage.cache_read_tokens,
                cache_write_tokens=turn.usage.cache_write_tokens,
            )
        return columns

    def _fold_turn_into_run(self, turn: AssistantTurn) -> None:
        """Sum the turn into the run aggregates as it lands, so an in-flight
        (or crashed) run's cost and progress are inspectable, not zeroed."""
        run = self.run
        run.iterations += 1
        if turn.usage is not None:
            run.input_tokens += turn.usage.input_tokens or 0
            run.output_tokens += turn.usage.output_tokens or 0
            run.cache_read_tokens += turn.usage.cache_read_tokens or 0
            run.cache_write_tokens += turn.usage.cache_write_tokens or 0
        run.save(
            update_fields=[
                "iterations",
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "updated_date",
            ]
        )

    def _finalize(
        self,
        *,
        status: str,
        stop_reason: str,
        iterations: int | None,
        error_message: str = "",
    ) -> None:
        # The agent suppresses recorder failures. An inner atomic block gives
        # database errors a savepoint to roll back before that suppression, so
        # a caller's surrounding transaction remains usable.
        with transaction.atomic():
            run = self.run
            run.status = status
            run.stop_reason = stop_reason
            if iterations is not None:
                run.iterations = iterations
            run.error_message = error_message
            run.finished_at = timezone.now()
            run.duration = run.finished_at - run.created_date
            run.save(
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
