"""Conversation and notebook-association services."""

from django.db import transaction
from django.db.models import Q

from research_ai.models import (
    AgentConversation,
    AgentConversationMessage,
    NoteAgentConversation,
)


class AgentConversationService:
    def create(
        self,
        *,
        user=None,
        workflow: str = "",
    ) -> AgentConversation:
        return AgentConversation.objects.create(
            user=user,
            workflow=workflow,
        )

    def add_human_message(
        self, conversation: AgentConversation, content: str
    ) -> AgentConversationMessage:
        with transaction.atomic():
            locked = AgentConversation.objects.select_for_update().get(
                id=conversation.id
            )
            message = AgentConversationMessage.objects.create(
                conversation=locked,
                sequence=locked.next_chat_sequence,
                role=AgentConversationMessage.Role.USER,
                content=content,
            )
            locked.next_chat_sequence += 1
            locked.save(update_fields=["next_chat_sequence", "updated_date"])
        return message


class NoteAgentConversationService:
    """Manage notebook-to-conversation associations."""

    def attach(self, conversation: AgentConversation, note) -> NoteAgentConversation:
        with transaction.atomic():
            link, _created = NoteAgentConversation.objects.get_or_create(
                note=note,
                conversation=conversation,
            )
        return link

    def for_note(self, note):
        # The proposal relation is a deterministic recovery path if the
        # best-effort join-table write failed after the proposal was completed.
        return (
            AgentConversation.objects.filter(
                Q(note_links__note=note) | Q(proposal_draft__note=note)
            )
            .distinct()
            .order_by("-updated_date", "-id")
        )
