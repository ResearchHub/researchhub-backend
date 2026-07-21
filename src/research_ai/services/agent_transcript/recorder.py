"""The database implementation of the agent core's ``AgentRecorder`` protocol.

Writes are incremental -- an entry per message as the loop appends it -- so the
transcript gives a live trace while a run is in progress, survives a hard
crash mid-run, and makes stuck runs inspectable. Transcript rows are insert-only:
the recorder never updates or deletes one after writing it; the mutable state
of a run lives on ``AgentRun``.

The loop swallows recorder exceptions (a transcript is observability; it must
not kill a run), so a persistence failure here costs rows, never the run.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from research_ai.models import (
    AgentChatMessage,
    AgentConversation,
    AgentRun,
    AgentTranscriptEntry,
)
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

    Creates the ``AgentRun`` row on construction, appends an
    ``AgentTranscriptEntry`` per recorded message (resuming the conversation's
    sequence counter), folds
    each assistant turn's usage into the run aggregates as it lands, and
    finalizes the run row on finish or fail.

    A chat-triggered run also links to one user ``AgentChatMessage`` and creates
    its final assistant chat message when the run completes. The internal
    transcript remains distinct from those product records.
    """

    def __init__(
        self,
        conversation: AgentConversation,
        *,
        model_id: str = "",
        config: dict | None = None,
        max_block_chars: int | None = None,
        prompt_source: str = AgentTranscriptEntry.Source.BACKEND,
        human_text: str | None = None,
        trigger_message: AgentChatMessage | None = None,
        retry_of: AgentRun | None = None,
    ):
        """``prompt_source`` labels the run's prompt turn: ``HUMAN`` when the
        text is a user's message sent verbatim (chat), ``BACKEND`` (default)
        when the backend composed it. For a backend-templated prompt that
        embeds a human's words, pass their verbatim text as ``human_text`` --
        it is stored as an explicit ``AgentChatMessage`` so the product never
        has to parse or render the provider prompt. A previously persisted
        ``trigger_message`` may be supplied for retries or async chat flows.
        """
        if trigger_message is not None:
            if trigger_message.conversation_id != conversation.id:
                raise ValueError("trigger_message must belong to the conversation")
            if trigger_message.role != AgentChatMessage.Role.USER:
                raise ValueError("trigger_message must be a user chat message")
        if retry_of is not None and retry_of.conversation_id != conversation.id:
            raise ValueError("retry_of must belong to the conversation")

        self.conversation = conversation
        self.prompt_source = prompt_source
        self.human_text = human_text
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
            trigger_message=trigger_message,
            retry_of=retry_of,
        )

    # -- AgentRecorder protocol -------------------------------------------

    def record_message(
        self, message: Message, *, turn: AssistantTurn | None = None
    ) -> None:
        serialized_content = serialize_messages([message])[0]["content"]
        content = [self._cap_block(block) for block in serialized_content]
        source = self._provenance(message.role, content)
        with transaction.atomic():
            # Conversations may have multiple overlapping runs. Lock the
            # shared parent while allocating the next sequence so two
            # recorders cannot claim the same position.
            AgentConversation.objects.select_for_update().only("pk").get(
                pk=self.conversation.pk
            )
            last_sequence = (
                AgentTranscriptEntry.objects.filter(conversation=self.conversation)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
            )
            sequence = 0 if last_sequence is None else last_sequence + 1
            entry = AgentTranscriptEntry.objects.create(
                conversation=self.conversation,
                run=self.run,
                sequence=sequence,
                role=message.role,
                source=source,
                content=content,
                **self._turn_columns(turn),
            )
            if turn is not None:
                self._fold_turn_into_run(turn)

        if self._is_chat_prompt(source):
            self._record_trigger_chat_message(entry, serialized_content)
        elif (
            message.role == AgentTranscriptEntry.Role.USER
            and source != AgentTranscriptEntry.Source.TOOL
            and self.run.trigger_message_id is not None
        ):
            self._link_trigger_transcript(entry)

    def on_run_finished(self, result: AgentResult) -> None:
        self._finalize(
            status=AgentRun.Status.COMPLETED,
            stop_reason=result.stop_reason,
            iterations=result.iterations,
        )
        self._record_output_chat_message(result)

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

    def _provenance(self, role: str, content: list[dict]) -> str:
        """Derive one transcript entry's provenance from its structure.

        Assistant rows and tool-result rows are structurally unambiguous. The
        remaining case -- a user row of ordinary blocks -- is the run's prompt
        turn, whose authorship only the caller knows, gets ``prompt_source``.
        """
        if role == AgentTranscriptEntry.Role.ASSISTANT:
            return AgentTranscriptEntry.Source.AGENT
        if content and all(block.get("type") == "tool_result" for block in content):
            return AgentTranscriptEntry.Source.TOOL
        return self.prompt_source

    def _is_chat_prompt(self, source: str) -> bool:
        return self.run.trigger_message_id is None and (
            source == AgentTranscriptEntry.Source.HUMAN or self.human_text is not None
        )

    def _record_trigger_chat_message(
        self, entry: AgentTranscriptEntry, provider_content: list[dict]
    ) -> None:
        """Persist and link the product message that triggered this run."""
        display_content = (
            [{"type": "text", "text": self.human_text}]
            if self.human_text is not None
            else provider_content
        )
        with transaction.atomic():
            AgentConversation.objects.select_for_update().only("pk").get(
                pk=self.conversation.pk
            )
            chat_message = AgentChatMessage.objects.create(
                conversation=self.conversation,
                sequence=self._next_chat_sequence(),
                role=AgentChatMessage.Role.USER,
                content=display_content,
                transcript_entry=entry,
            )
            self.run.trigger_message = chat_message
            self.run.save(update_fields=["trigger_message", "updated_date"])

    def _record_output_chat_message(self, result: AgentResult) -> None:
        """Create the final assistant product message for a chat-triggered run."""
        if self.run.trigger_message_id is None or not result.final_text.strip():
            return
        entry = (
            self.run.transcript_entries.filter(role=AgentTranscriptEntry.Role.ASSISTANT)
            .order_by("-sequence")
            .first()
        )
        if entry is None:
            return
        display_content = [
            block
            for block in entry.content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if not display_content:
            return
        with transaction.atomic():
            AgentConversation.objects.select_for_update().only("pk").get(
                pk=self.conversation.pk
            )
            AgentChatMessage.objects.get_or_create(
                transcript_entry=entry,
                defaults={
                    "conversation": self.conversation,
                    "sequence": self._next_chat_sequence(),
                    "role": AgentChatMessage.Role.ASSISTANT,
                    "content": display_content,
                    "produced_by_run": self.run,
                    "reply_to": self.run.trigger_message,
                },
            )

    def _link_trigger_transcript(self, entry: AgentTranscriptEntry) -> None:
        """Link a pre-existing user chat message to its first provider entry."""
        AgentChatMessage.objects.filter(
            pk=self.run.trigger_message_id,
            transcript_entry__isnull=True,
        ).update(transcript_entry=entry)

    def _next_chat_sequence(self) -> int:
        last_sequence = (
            AgentChatMessage.objects.filter(conversation=self.conversation)
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        )
        return 0 if last_sequence is None else last_sequence + 1

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
