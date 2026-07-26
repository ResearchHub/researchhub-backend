"""Reusable, provider-agnostic, tool-using agent core.

Public surface:

- Neutral types: ``Message``, ``TextBlock``, ``ThinkingBlock``,
  ``ToolUseBlock``, ``ToolResultBlock``, ``AssistantTurn``, ``TurnUsage``,
  ``StopReason``, and the ``serialize_messages`` / ``deserialize_messages``
  helpers.
- Tools: ``Tool``, ``Toolset``.
- Providers: ``LLMProvider`` (ABC), ``BedrockProvider``,
  ``ClaudePlatformProvider``, and the settings-driven resolvers
  ``resolve_provider`` / ``generator_model_ref``.
- Loop: ``Agent``, ``AgentResult``.
- Recording: ``AgentRecorder`` (protocol; implementations live outside the
  package and are injected).
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
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.registry import (
    generator_model_ref,
    resolve_provider,
)
from research_ai.services.agent.recorder import AgentRecorder
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    TurnUsage,
    deserialize_messages,
    serialize_messages,
)

__all__ = [
    "Agent",
    "AgentRecorder",
    "AgentResult",
    "AgentRunError",
    "AgentService",
    "AssistantTurn",
    "BedrockProvider",
    "ClaudePlatformProvider",
    "IncompleteTurnError",
    "IterationLimitError",
    "LLMProvider",
    "ProviderError",
    "Message",
    "StopReason",
    "TextBlock",
    "ThinkingBlock",
    "Tool",
    "ToolResultBlock",
    "ToolUseBlock",
    "Toolset",
    "TurnUsage",
    "deserialize_messages",
    "generator_model_ref",
    "resolve_provider",
    "serialize_messages",
]
