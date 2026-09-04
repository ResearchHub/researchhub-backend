"""The research assistant chat: the notebook agent without a routed note.

A user keeps any number of assistant chats, workflow ``assistant_chat``, each
an ``AgentConversation`` scoped to its owner and resolved by id. Turns run on
the notebook chat engine (``NotebookChatService``) with no note: the agent
researches with the same tools and may call ``create_note``, which creates a
private note in the user's notebook and attaches it to the conversation. The
attached notes are the only ones the chat can read or edit, and they are
reported on the chat representation so a client can link to them.

The notebook chat list for a note filters on its own workflow, so a note this
flow created does not show the assistant chat among that note's chats.
"""

from research_ai.models import AgentConversation, AgentExecution
from research_ai.services.notebook_chat.service import (
    ACTIVITY_ALL,
    ASSISTANT_WORKFLOW,
    NotebookChatService,
)

WORKFLOW = ASSISTANT_WORKFLOW


class AssistantChatService:
    """User-scoped chat operations over the shared turn engine.

    ``engine`` is injectable for tests; every other keyword argument is
    passed through to ``NotebookChatService``.
    """

    def __init__(self, *, engine: NotebookChatService | None = None, **engine_kwargs):
        self.engine = (
            NotebookChatService(workflow=WORKFLOW, **engine_kwargs)
            if engine is None
            else engine
        )

    # -- request path -----------------------------------------------------

    def get_conversation(self, user, conversation_id: int) -> AgentConversation | None:
        """The user's assistant chat ``conversation_id``, if any."""
        return AgentConversation.objects.filter(
            workflow=WORKFLOW, user=user, id=conversation_id
        ).first()

    def list_conversations(self, user) -> list[dict]:
        """The user's assistant chats, newest activity first."""
        conversations = self.engine.listing(
            AgentConversation.objects.filter(workflow=WORKFLOW, user=user).order_by(
                "-updated_date", "-id"
            )
        )
        return [
            {
                "id": conversation.id,
                "title": conversation.title,
                "created_date": conversation.created_date,
                "updated_date": conversation.updated_date,
                "last_message_preview": conversation.last_message_preview,
                "has_active_turn": conversation.has_active_turn,
            }
            for conversation in conversations
        ]

    def create_conversation(self, user, title: str = "") -> AgentConversation:
        return self.engine.conversations.create(
            user=user, workflow=WORKFLOW, title=title
        )

    def rename_conversation(
        self, conversation: AgentConversation, title: str
    ) -> AgentConversation:
        return self.engine.rename_conversation(conversation, title)

    def representation(
        self, conversation: AgentConversation, *, activity_scope: str = ACTIVITY_ALL
    ) -> dict:
        """The notebook chat projection plus the notes this chat created."""
        data = self.engine.representation(conversation, activity_scope=activity_scope)
        data["notes"] = [
            {"id": note.id, "title": note.title}
            for note in self.engine._linked_notes(conversation)
        ]
        return data

    def submit_message(
        self, conversation: AgentConversation, text: str, **options
    ) -> AgentExecution:
        return self.engine.submit_message(None, conversation, text, **options)

    def cancel_active_turn(
        self, conversation: AgentConversation
    ) -> AgentExecution | None:
        return self.engine.cancel_active_turn(conversation)

    # -- worker path ------------------------------------------------------

    def run_turn(self, execution_id: int) -> dict:
        return self.engine.run_turn(execution_id)
