"""Durable model-context reconstruction services."""

from django.db import transaction

from research_ai.models import AgentContextMessage, AgentConversation, AgentExecution
from research_ai.services.agent.types import (
    Message,
    ToolResultBlock,
    ToolUseBlock,
    deserialize_messages,
)
from research_ai.services.agent_persistence.content import serialize_context_message

INTERRUPTED_TOOL_RESULT = {
    "type": "text",
    "text": "The tool call did not finish because the agent run stopped.",
}


def _unanswered_tool_use_ids(messages: list[Message]) -> list[str]:
    """Return tool calls in ``messages`` that no later result ever answered."""
    answered = {
        block.tool_use_id
        for message in messages
        for block in message.content
        if isinstance(block, ToolResultBlock)
    }
    return [
        block.id
        for message in messages
        for block in message.content
        if isinstance(block, ToolUseBlock) and block.id not in answered
    ]


class AgentContextService:
    def reconstruct(self, execution: AgentExecution) -> list[Message]:
        """Rebuild the durable, explicitly compacted context lineage."""
        lineage: list[AgentExecution] = []
        seen: set[int] = set()
        current = execution
        while current is not None:
            if (
                current.id in seen
                or current.conversation_id != execution.conversation_id
            ):
                raise ValueError("invalid agent execution context lineage")
            seen.add(current.id)
            lineage.append(current)
            current = current.context_parent
        lineage.reverse()

        serialized_messages = []
        for item in lineage:
            serialized_messages.extend(
                item.context_messages.order_by("sequence").values(
                    "role", "content", "provider_state"
                )
            )
        return deserialize_messages(serialized_messages)

    def latest_for_continuation(
        self, conversation: AgentConversation, *, include_partial: bool = False
    ) -> AgentExecution | None:
        """Return the execution whose durable context a new attempt extends."""
        statuses = [AgentExecution.Status.SUCCEEDED]
        if include_partial:
            # A stopped run holds durable context rows, including the human
            # prompt that triggered it. CANCELLED and INTERRUPTED are the same
            # user intent recorded from different sides: INTERRUPTED when the
            # worker observed the stop in-process, CANCELLED when another
            # process flipped the row. Excluding either would silently resume an
            # older attempt and drop a user-visible prompt.
            statuses.extend(
                [
                    AgentExecution.Status.FAILED,
                    AgentExecution.Status.INTERRUPTED,
                    AgentExecution.Status.CANCELLED,
                ]
            )
        return (
            conversation.executions.filter(status__in=statuses)
            .order_by("-attempt")
            .first()
        )

    def for_continuation(
        self, conversation: AgentConversation, *, include_partial: bool = False
    ) -> list[Message]:
        execution = self.latest_for_continuation(
            conversation, include_partial=include_partial
        )
        return self.reconstruct(execution) if execution else []

    def seal_interrupted_tool_calls(self, execution: AgentExecution) -> int:
        """Answer tool calls a stopped run left open, so its context can resume.

        A run recorded its tool calls before dispatching them, so stopping in
        between leaves a durable ``tool_use`` with no ``tool_result``. Providers
        reject that pairing on replay, and the gap is permanent once a later
        attempt chains onto these rows. Closing it with an explicit error result
        keeps the lineage valid without editing or dropping what was recorded:
        block order and signed reasoning must survive untouched.

        Returns the number of tool calls sealed, and is a no-op when the
        recorded context is already complete.
        """
        with transaction.atomic():
            locked = AgentExecution.objects.select_for_update().get(id=execution.id)
            unanswered = _unanswered_tool_use_ids(self.reconstruct(locked))
            if not unanswered:
                return 0
            content, provider_state, is_compacted, original_size = (
                serialize_context_message(
                    Message(
                        role="user",
                        content=[
                            ToolResultBlock(
                                tool_use_id=tool_use_id,
                                content=INTERRUPTED_TOOL_RESULT,
                                is_error=True,
                            )
                            for tool_use_id in unanswered
                        ],
                    )
                )
            )
            AgentContextMessage.objects.create(
                execution=locked,
                sequence=locked.next_context_sequence,
                role="user",
                content=content,
                provider_state=provider_state,
                is_compacted=is_compacted,
                original_size_bytes=(original_size if is_compacted else None),
            )
            locked.next_context_sequence += 1
            locked.save(update_fields=["next_context_sequence", "updated_date"])
        return len(unanswered)
