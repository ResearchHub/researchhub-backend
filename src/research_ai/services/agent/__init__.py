"""Reusable, provider-agnostic, tool-using agent core.

Public surface:

- Neutral types: ``Message``, ``TextBlock``, ``ToolUseBlock``,
  ``ToolResultBlock``, ``AssistantTurn``, ``TurnUsage``, ``StopReason``, and the
  ``serialize_messages`` / ``deserialize_messages`` helpers.
- Recorder: ``AgentRecorder``.
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
from research_ai.services.agent.recorder import AgentRecorder
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
    deserialize_messages,
    serialize_messages,
)

__all__ = [
    "Agent",
    "AgentResult",
    "AgentRunError",
    "AgentRecorder",
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
    "TurnUsage",
    "deserialize_messages",
    "serialize_messages",
]
