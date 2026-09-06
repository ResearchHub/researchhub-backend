"""The notebook chat assistant flow."""

from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.events import (
    ConversationEventPublisher,
    conversation_group,
)
from research_ai.services.notebook_chat.grant_tools import (
    READ_SELECTED_RFP,
    SET_SELECTED_RFP,
    GrantSearchToolset,
    SelectedRFPToolset,
)
from research_ai.services.notebook_chat.researcher_profile_tools import (
    GET_RESEARCHER_PROFILE,
    ResearcherProfileToolset,
)
from research_ai.services.notebook_chat.service import (
    ACTIVITY_ALL,
    ACTIVITY_LIVE,
    ASSISTANT_WORKFLOW,
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
    "ASSISTANT_WORKFLOW",
    "GET_RESEARCHER_PROFILE",
    "READ_SELECTED_RFP",
    "SET_SELECTED_RFP",
    "WORKFLOW",
    "ConversationEventPublisher",
    "GrantSearchToolset",
    "NotebookChatConfig",
    "NotebookChatService",
    "NotebookWebSearchToolset",
    "ResearcherProfileToolset",
    "SelectedRFPToolset",
    "compose_notebook_toolset",
    "conversation_group",
]
