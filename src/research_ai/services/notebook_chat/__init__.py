"""The notebook chat assistant flow."""

from research_ai.services.notebook_chat.config import NotebookChatConfig
from research_ai.services.notebook_chat.service import WORKFLOW, NotebookChatService
from research_ai.services.notebook_chat.toolset import (
    NotebookWebSearchToolset,
    compose_notebook_toolset,
)

__all__ = [
    "NotebookChatConfig",
    "NotebookChatService",
    "NotebookWebSearchToolset",
    "WORKFLOW",
    "compose_notebook_toolset",
]
