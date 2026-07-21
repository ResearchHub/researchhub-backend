"""Serialize the product chat messages for an agent conversation."""

from research_ai.models import AgentConversation


def _text_of(content: list) -> str:
    """The visible text of a row: its text blocks joined, other blocks ignored."""
    texts = [
        block.get("text", "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "\n\n".join(text for text in texts if text.strip())


def build_chat_view(conversation: AgentConversation) -> list[dict]:
    """Return the conversation's explicit user-facing messages in order."""
    return [
        {
            "id": message.id,
            "sequence": message.sequence,
            "sender": "agent" if message.role == "assistant" else "user",
            "text": _text_of(message.content),
            "timestamp": message.created_date,
            "run_id": message.produced_by_run_id,
        }
        for message in conversation.chat_messages.order_by("sequence")
    ]
