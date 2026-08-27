"""Explicit retention services for disposable execution traces."""

from datetime import datetime, timedelta

from django.utils import timezone

from research_ai.models import AgentConversation, AgentExecution, AgentExecutionMessage

# How long observational trace rows stay before the scheduled sweep removes
# them. Chat messages and context lineage are unaffected -- see the service.
TRACE_RETENTION = timedelta(days=30)

# Rows deleted per query during the sweep, so the first run over a large
# backlog holds no long transaction.
_DELETE_BATCH_SIZE = 5_000


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

    def delete_stale_traces(
        self,
        *,
        older_than: timedelta = TRACE_RETENTION,
        now: datetime | None = None,
    ) -> int:
        """Delete trace rows past the retention window; return how many.

        Same scope rule as above: only ``AgentExecutionMessage`` rows go.
        Context lineage must survive indefinitely -- an old chat's next turn
        still reconstructs from it -- and chat messages are the product.
        """
        cutoff = (timezone.now() if now is None else now) - older_than
        total = 0
        while True:
            batch = list(
                AgentExecutionMessage.objects.filter(
                    created_date__lt=cutoff
                ).values_list("id", flat=True)[:_DELETE_BATCH_SIZE]
            )
            if not batch:
                return total
            deleted, _ = AgentExecutionMessage.objects.filter(id__in=batch).delete()
            total += deleted
