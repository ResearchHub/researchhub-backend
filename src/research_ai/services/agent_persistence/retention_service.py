"""Explicit retention services for disposable execution traces."""

from research_ai.models import AgentConversation, AgentExecution


class AgentRetentionService:
    """Remove debugging data without deleting chat or domain output."""

    def delete_execution_trace(self, execution: AgentExecution) -> int:
        deleted, _ = execution.messages.all().delete()
        return deleted

    def delete_conversation_debug(self, conversation: AgentConversation) -> None:
        # Executions and context lineage are workflow state needed for retries,
        # pending/failure markers, and continuation. Only observational trace
        # rows are disposable.
        conversation.trace_messages.all().delete()
