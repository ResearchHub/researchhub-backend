"""Reusable, provider-agnostic, tool-using agent core.

Public surface:

- Neutral types: ``Message``, ``TextBlock``, ``ToolUseBlock``,
  ``ToolResultBlock``, ``AssistantTurn``, ``StopReason``, and the
  ``serialize_messages`` / ``deserialize_messages`` helpers.
- Tools: ``Tool``, ``Toolset``.
- Providers: ``LLMProvider`` (ABC), ``BedrockProvider``.
- Loop: ``Agent``, ``AgentResult``.
- Errors: ``AgentRunError`` and its subclasses ``ProviderError``,
  ``IncompleteTurnError``, ``IterationLimitError``.
- Factory: ``AgentService``.

Importing this package has no side effects (no network, no Django models).
"""

from research_ai.services.agent.agent_service import AgentService
from research_ai.services.agent.errors import (
    AgentRunError,
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.loop import Agent, AgentResult
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    deserialize_messages,
    serialize_messages,
)

__all__ = [
    "Agent",
    "AgentResult",
    "AgentRunError",
    "AgentService",
    "AssistantTurn",
    "BedrockProvider",
    "IncompleteTurnError",
    "IterationLimitError",
    "LLMProvider",
    "ProviderError",
    "Message",
    "StopReason",
    "TextBlock",
    "Tool",
    "ToolResultBlock",
    "ToolUseBlock",
    "Toolset",
    "deserialize_messages",
    "serialize_messages",
]
