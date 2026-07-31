"""Regeneration lineage shared by assistant-output publication and repair.

Regenerations chain: C replaces B, which replaced A. Both publication and
repair have to read that chain transitively, because a link that never
published a message of its own supersedes nothing by itself and would
otherwise conceal the answer behind it.
"""

from research_ai.models import AgentConversation, AgentExecution


def _walk_replaced(
    parents: dict[int, int | None], start_id: int, seen: set[int]
) -> None:
    """Collect the replacement ancestors of ``start_id`` into ``seen``."""
    current = parents.get(start_id)
    while current is not None and current not in seen:
        seen.add(current)
        current = parents.get(current)


def replaced_execution_ids(execution: AgentExecution) -> list[int]:
    """Return every earlier answer that publishing ``execution`` supersedes."""
    parents = dict(
        AgentExecution.objects.filter(
            conversation_id=execution.conversation_id
        ).values_list("id", "replaces_output_of_id")
    )
    replaced: set[int] = set()
    _walk_replaced(parents, execution.id, replaced)
    return list(replaced)


def superseded_execution_ids(conversation: AgentConversation) -> set[int]:
    """Return executions whose answer a later regeneration already published.

    Walking up from each attempt that published keeps an unpublished link in
    the chain from hiding the ancestors behind it. Deactivated messages still
    count as published: their attempt answered, and a further regeneration has
    since replaced it.
    """
    rows = list(
        conversation.executions.values_list(
            "id", "replaces_output_of_id", "generated_chat_message__id"
        )
    )
    parents = {execution_id: parent_id for execution_id, parent_id, _ in rows}
    superseded: set[int] = set()
    for execution_id, _parent_id, message_id in rows:
        if message_id is not None:
            _walk_replaced(parents, execution_id, superseded)
    return superseded
