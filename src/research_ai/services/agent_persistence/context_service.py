"""Durable model-context reconstruction services."""

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.agent.types import Message, deserialize_messages


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
                item.context_messages.order_by("sequence").values("role", "content")
            )
        return deserialize_messages(serialized_messages)

    def for_continuation(
        self, conversation: AgentConversation, *, include_partial: bool = False
    ) -> list[Message]:
        statuses = [AgentExecution.Status.SUCCEEDED]
        if include_partial:
            statuses.extend(
                [AgentExecution.Status.FAILED, AgentExecution.Status.INTERRUPTED]
            )
        execution = (
            conversation.executions.filter(status__in=statuses)
            .order_by("-attempt")
            .first()
        )
        return self.reconstruct(execution) if execution else []
