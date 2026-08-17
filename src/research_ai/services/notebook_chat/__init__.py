"""The notebook chat assistant flow."""

from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.events import (
    ConversationEventPublisher,
    conversation_group,
)
from research_ai.services.notebook_chat.grant_tools import GrantSearchToolset
from research_ai.services.notebook_chat.service import (
    ACTIVITY_ALL,
    ACTIVITY_LIVE,
    WORKFLOW,
    NotebookChatService,
)
from research_ai.services.notebook_chat.toolset import (
    NotebookWebSearchToolset,
    compose_notebook_toolset,
)

__all__ = [
    "ACTIVITY_ALL",
    "ACTIVITY_LIVE",
    "WORKFLOW",
    "ConversationEventPublisher",
    "GrantSearchToolset",
    "NotebookChatConfig",
    "NotebookChatService",
    "NotebookWebSearchToolset",
    "compose_notebook_toolset",
    "conversation_group",
]
