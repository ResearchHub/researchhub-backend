"""User-facing chat preparation and representation services."""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction

from research_ai.models import (
    AgentConversation,
    AgentConversationMessage,
    AgentExecution,
    AgentExecutionMessage,
)
from research_ai.services.agent.types import Message
from research_ai.services.agent_persistence.context_service import AgentContextService
from research_ai.services.agent_persistence.conversation_service import (
    AgentConversationService,
)
from research_ai.services.agent_persistence.execution_service import (
    AgentExecutionService,
)
from research_ai.services.agent_persistence.recorder import DatabaseAgentRecorder
from research_ai.services.agent_persistence.replacement import (
    superseded_execution_ids,
)

logger = logging.getLogger(__name__)

RecorderFactory = Callable[..., DatabaseAgentRecorder]


def _has_publishable_output(execution: AgentExecution) -> bool:
    """Report whether a successful attempt left text the chat can show.

    A run that ends on a terminal tool answers through that tool and records no
    final text. Its result is domain output rather than conversation, so there
    is nothing to publish and nothing to keep waiting for.
    """
    output = execution.final_output
    text = output.get("text") if isinstance(output, dict) else None
    return isinstance(text, str) and bool(text)


def _max_iterations(execution: AgentExecution) -> int | None:
    """The iteration ceiling this attempt was submitted with, if it recorded one.

    Read from the execution's own configuration snapshot rather than current
    settings, so a client rendering "step 4 of 30" shows the bound the run is
    actually held to and not one a later settings change invented.
    """
    configuration = execution.configuration
    if not isinstance(configuration, dict):
        return None
    value = configuration.get("max_iterations")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass(frozen=True)
class PreparedAgentExecution:
    execution: AgentExecution
    # None when the turn was prepared ``pending``: the recorder is created by
    # whichever worker claims the execution, not at preparation time.
    recorder: DatabaseAgentRecorder | None
    human_message: AgentConversationMessage | None
    context: list[Message]


class AgentChatService:
    def __init__(
        self,
        *,
        conversation_service: AgentConversationService | None = None,
        execution_service: AgentExecutionService | None = None,
        context_service: AgentContextService | None = None,
        recorder_factory: RecorderFactory | None = None,
    ):
        self.conversations = (
            AgentConversationService()
            if conversation_service is None
            else conversation_service
        )
        self.executions = (
            AgentExecutionService(recorder_factory=recorder_factory)
            if execution_service is None
            else execution_service
        )
        self.contexts = (
            AgentContextService() if context_service is None else context_service
        )
        self.recorder_factory = (
            getattr(self.executions, "recorder_factory", DatabaseAgentRecorder)
            if recorder_factory is None
            else recorder_factory
        )

    def prepare_turn(
        self,
        conversation: AgentConversation,
        human_content: str,
        *,
        provider: str = "",
        model: str = "",
        configuration: dict | None = None,
        system_prompt: str = "",
        prompt_is_backend_composed: bool = False,
        pending: bool = False,
    ) -> PreparedAgentExecution:
        """Append the user's message and create the turn's execution.

        With ``pending=True`` the execution is created ``PENDING`` for a
        worker to claim via ``executions.claim_pending`` (which also picks the
        prompt provenance), and the returned ``recorder`` is ``None``.
        """
        with transaction.atomic():
            locked = AgentConversation.objects.select_for_update().get(
                id=conversation.id
            )
            # Land any answer still waiting to publish before this question
            # takes the next sequence. Publication numbers a message when it
            # succeeds, not when its run finished, so repairing afterwards
            # would file the previous answer behind the question that follows
            # it -- an order the model's own context contradicts.
            self.repair_pending_outputs(locked)
            # A new turn continues from the latest stopped attempt as well as
            # the latest successful one: a run that failed after recording its
            # prompt still holds user-visible context, and skipping back to an
            # older attempt would drop it from the model's view while the chat
            # still shows it.
            parent = self.contexts.latest_for_continuation(locked, include_partial=True)
            if parent is not None:
                self.contexts.seal_interrupted_tool_calls(parent)
            context = self.contexts.reconstruct(parent) if parent else []
            human_message = self.conversations.add_human_message(locked, human_content)
            if pending:
                execution = self.executions.create_pending(
                    locked,
                    provider=provider,
                    model=model,
                    configuration=configuration,
                    system_prompt=system_prompt,
                    trigger_message=human_message,
                    context_parent=parent,
                    publish_assistant_message=True,
                )
                recorder = None
            else:
                recorder = self.executions.start(
                    locked,
                    provider=provider,
                    model=model,
                    configuration=configuration,
                    system_prompt=system_prompt,
                    trigger_message=human_message,
                    context_parent=parent,
                    initial_prompt_provenance=(
                        AgentExecutionMessage.Provenance.BACKEND
                        if prompt_is_backend_composed
                        else AgentExecutionMessage.Provenance.HUMAN
                    ),
                    publish_assistant_message=True,
                )
                execution = recorder.execution
        return PreparedAgentExecution(execution, recorder, human_message, context)

    @staticmethod
    def _retry_provenance(execution: AgentExecution) -> str:
        """Reuse the provenance the original attempt recorded for its prompt.

        Only the first trace row can answer this. Trace writes are best-effort,
        so a later row surviving on its own says nothing about who wrote the
        prompt -- reading whichever row came first would label a human prompt
        ``MODEL`` or ``TOOL``.
        """
        provenance = (
            execution.messages.filter(execution_sequence=1)
            .values_list("provenance", flat=True)
            .first()
        )
        if provenance in AgentExecutionMessage.Provenance.values:
            return provenance
        if execution.trigger_message_id:
            return AgentExecutionMessage.Provenance.HUMAN
        return AgentExecutionMessage.Provenance.BACKEND

    def prepare_retry(
        self,
        execution: AgentExecution,
        *,
        configuration: dict | None = None,
        system_prompt: str | None = None,
        regenerate: bool = False,
        initial_prompt_provenance: str | None = None,
    ) -> PreparedAgentExecution:
        context = (
            self.contexts.reconstruct(execution.context_parent)
            if execution.context_parent
            else []
        )
        recorder = self.executions.start(
            execution.conversation,
            provider=execution.provider,
            model=execution.model,
            configuration=(
                execution.configuration if configuration is None else configuration
            ),
            system_prompt=(
                execution.system_prompt if system_prompt is None else system_prompt
            ),
            trigger_message=execution.trigger_message,
            context_parent=execution.context_parent,
            retry_of=execution,
            initial_prompt_provenance=(
                self._retry_provenance(execution)
                if initial_prompt_provenance is None
                else initial_prompt_provenance
            ),
            publish_assistant_message=True,
            replaces_output_of=execution if regenerate else None,
        )
        return PreparedAgentExecution(
            recorder.execution, recorder, execution.trigger_message, context
        )

    @staticmethod
    def _public_error(execution: AgentExecution) -> dict[str, str] | None:
        if not execution.error_type:
            return None
        if execution.status == AgentExecution.Status.INTERRUPTED:
            return {
                "code": "agent_interrupted",
                "message": "The agent request was interrupted.",
            }
        return {
            "code": "agent_failed",
            "message": "The agent could not complete this request.",
        }

    def representation(self, conversation: AgentConversation) -> dict:
        """Repair pending publication and return user-safe chat lifecycle data.

        ``repaired_execution_ids`` reports the publications that landed during
        this very read. The transition is invisible in the rest of the payload
        -- the turn was ``SUCCEEDED`` before and after -- yet it changes how
        the turn's activity renders, and a caller scoping that work to "what
        could have changed" would otherwise skip exactly the turn that just
        did.
        """
        repaired = self.repair_pending_outputs(conversation)
        # Skew here is safe in the one direction it can go: an answer published
        # after this read is reported still pending, which costs a poll. Reading
        # it later could not report a live answer as already superseded.
        superseded = superseded_execution_ids(conversation)
        # One read answers both what the chat shows and what is still pending.
        # Asking the execution rows instead would let a publication landing
        # between the two queries report an answer as delivered while the
        # message list that should carry it was read a moment too early.
        chat_messages = list(conversation.chat_messages.order_by("sequence"))
        published = {
            message.generated_by_execution_id
            for message in chat_messages
            if message.generated_by_execution_id is not None
        }
        messages = [
            {
                "id": message.id,
                "sequence": message.sequence,
                "role": message.role.lower(),
                "content": message.content,
                "execution_id": message.generated_by_execution_id,
            }
            for message in chat_messages
            if message.is_active
        ]
        executions = [
            {
                "id": execution.id,
                "attempt": execution.attempt,
                "status": execution.status,
                "trigger_message_id": execution.trigger_message_id,
                "retry_of_id": execution.retry_of_id,
                "context_parent_id": execution.context_parent_id,
                "stop_reason": execution.stop_reason,
                # Progress signals. ``last_activity_at`` is the run's heartbeat
                # -- the recorder stamps it on every durable write -- so a
                # client can tell a turn that is working slowly from one that
                # has gone quiet, well before the liveness sweep reclaims it.
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "last_activity_at": execution.last_activity_at,
                "iterations": execution.iterations,
                "max_iterations": _max_iterations(execution),
                "assistant_message_pending": (
                    execution.status == AgentExecution.Status.SUCCEEDED
                    and execution.publish_output_to_chat
                    and execution.id not in published
                    and _has_publishable_output(execution)
                    and execution.id not in superseded
                ),
                "error": self._public_error(execution),
            }
            for execution in conversation.executions.order_by("attempt")
        ]
        return {
            "conversation_id": conversation.id,
            "messages": messages,
            "executions": executions,
            "repaired_execution_ids": repaired,
        }

    def repair_pending_outputs(self, conversation: AgentConversation) -> list[int]:
        """Retry any successful chat publication that previously failed.

        Two kinds of success are skipped before publication is even attempted:
        an answer a regeneration already published, and an answer with no final
        text. Neither can ever publish, so calling through would take two row
        locks on every read to be refused. Publication re-checks supersession
        under its own lock, so this pass is an optimisation, not the guarantee.

        Returns the ids of executions whose answer published on this pass. A
        publication landing changes how the turn presents -- its final text
        moves out of the working feed and into the chat -- so a caller that
        serves a scoped projection needs to know which turns transitioned
        under the read it is building.
        """
        candidates = [
            execution
            for execution in conversation.executions.filter(
                status=AgentExecution.Status.SUCCEEDED,
                publish_output_to_chat=True,
                generated_chat_message__isnull=True,
            ).order_by("attempt")
            if _has_publishable_output(execution)
        ]
        if not candidates:
            return []
        superseded = superseded_execution_ids(conversation)
        repaired = []
        for execution in candidates:
            if execution.id in superseded:
                continue
            try:
                # A savepoint keeps a failed repair from poisoning a caller's
                # transaction: prepare_turn repairs inside the lock it holds to
                # add the next question, and swallowing a database error
                # without one would break every write that follows.
                with transaction.atomic():
                    if self.recorder_factory(execution).publish_assistant_output():
                        repaired.append(execution.id)
            except Exception:  # noqa: BLE001 - reads still expose pending state
                logger.warning(
                    "failed to repair agent response publication",
                    exc_info=True,
                )
        return repaired
