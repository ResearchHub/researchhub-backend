"""The one place a stored transcript becomes a provider context.

Every resume path (the notebook chat's ``continue_conversation``, any future
flow) goes through ``build_context`` rather than reading rows directly, so how
a transcript turns into the message list the model sees stays a single,
swappable decision. In v1 the derivation is trivial: the full history in
sequence order.
"""

from research_ai.models import AgentConversation
from research_ai.services.agent import Message, deserialize_messages


def build_context(conversation: AgentConversation) -> list[Message]:
    """Rebuild the provider message list from ``conversation``'s stored rows."""
    rows = conversation.messages.order_by("sequence").values_list("role", "content")
    return deserialize_messages(
        [{"role": role, "content": content} for role, content in rows],
        ignore_unknown_blocks=True,
    )
