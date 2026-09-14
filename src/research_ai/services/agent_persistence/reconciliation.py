"""Reconcile a stopped run's durable context with the chat the user can see.

A run stopped partway leaves the two disagreeing in either direction: a turn
stopped before it ran never recorded the prompt the chat shows, and a turn
stopped just after its last answer recorded an answer the chat never received.
The next turn continues from this context, so both are repaired here.
"""

import logging

from research_ai.models import AgentContextMessage, AgentExecution
from research_ai.services.agent.types import Message, TextBlock
from research_ai.services.agent_persistence.content import serialize_context_message

logger = logging.getLogger(__name__)


def reconcile_stopped_run(execution: AgentExecution) -> None:
    """Apply both repairs to a run just sealed from outside its worker."""
    preserve_trigger_prompt(execution)
    drop_unpublished_answer(execution)


def preserve_trigger_prompt(execution: AgentExecution) -> None:
    """Seed an empty context with the chat prompt the run never recorded.

    A ``RUNNING`` turn records its prompt first thing, but one stopped while
    still ``PENDING`` never ran, and its prompt lives only in the chat message
    that triggered it.
    """
    if execution.context_messages.exists():
        return
    trigger = execution.trigger_message
    if trigger is None or not (trigger.content or "").strip():
        return
    content, provider_state, is_compacted, original_size = serialize_context_message(
        Message(role="user", content=[TextBlock(text=trigger.content)])
    )
    AgentContextMessage.objects.create(
        execution=execution,
        sequence=execution.next_context_sequence,
        role="user",
        content=content,
        provider_state=provider_state,
        is_compacted=is_compacted,
        original_size_bytes=original_size if is_compacted else None,
    )
    execution.next_context_sequence += 1
    execution.save(update_fields=["next_context_sequence", "updated_date"])


def drop_unpublished_answer(execution: AgentExecution) -> None:
    """Forget a closing answer the run recorded but never published.

    Publication requires ``SUCCEEDED``, so a run sealed any other way never
    delivers its last answer. Only a *closing* answer goes: an assistant turn
    holding tool calls is lineage a later turn seals, and dropping it would
    leave tool results with nothing to attach to.
    """
    if not execution.publish_output_to_chat:
        return
    last = execution.context_messages.order_by("-sequence").first()
    if last is None or last.role != "assistant":
        return
    blocks = last.content if isinstance(last.content, list) else []
    if any(
        isinstance(block, dict) and block.get("type") == "tool_use" for block in blocks
    ):
        return
    last.delete()
    logger.info(
        "dropped an unpublished answer from a stopped turn",
        extra={"execution_id": execution.id},
    )
