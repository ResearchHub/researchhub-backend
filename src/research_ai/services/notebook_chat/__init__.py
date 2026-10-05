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
from research_ai.services.notebook_chat.rfp_details_tools import (
    READ_RFP_DETAILS,
    UPDATE_RFP_DETAILS,
    RFPDetailsToolset,
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
    "READ_RFP_DETAILS",
    "READ_SELECTED_RFP",
    "SET_SELECTED_RFP",
    "UPDATE_RFP_DETAILS",
    "WORKFLOW",
    "ConversationEventPublisher",
    "GrantSearchToolset",
    "NotebookChatConfig",
    "NotebookChatService",
    "NotebookWebSearchToolset",
    "RFPDetailsToolset",
    "ResearcherProfileToolset",
    "SelectedRFPToolset",
    "compose_notebook_toolset",
    "conversation_group",
]
