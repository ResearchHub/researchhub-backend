"""Reusable, provider-agnostic, tool-using agent core.

Public surface:

- Neutral types: ``Message``, ``TextBlock``, ``ThinkingBlock``,
  ``ServerToolBlock``, ``ToolUseBlock``, ``ToolResultBlock``, ``AssistantTurn``,
  ``TurnUsage``, ``StopReason``, and the ``serialize_messages`` /
  ``deserialize_messages`` helpers.
- Tools: ``Tool``, ``Toolset``.
- Providers: ``LLMProvider`` (ABC), ``BedrockProvider``,
  ``ClaudePlatformProvider``, ``OpenRouterProvider``, and the settings-driven
  resolvers ``resolve_provider`` / ``generator_model_ref`` /
  ``split_model_ref``.
- Model catalog: ``ModelOption``, ``available_models``, ``default_model_ref``,
  ``validate_model_ref`` -- the allowlist behind user model selection.
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
    BudgetExceededError,
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.loop import Agent, AgentResult
from research_ai.services.agent.model_catalog import (
    ModelOption,
    available_models,
    default_model_ref,
    validate_model_ref,
)
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.providers.bedrock import BedrockProvider
from research_ai.services.agent.providers.claude_platform import ClaudePlatformProvider
from research_ai.services.agent.providers.openrouter import OpenRouterProvider
from research_ai.services.agent.providers.registry import (
    generator_model_ref,
    resolve_provider,
    split_model_ref,
)
from research_ai.services.agent.recorder import AgentRecorder
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    ServerToolBlock,
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
    "BudgetExceededError",
    "ClaudePlatformProvider",
    "IncompleteTurnError",
    "IterationLimitError",
    "LLMProvider",
    "Message",
    "ModelOption",
    "OpenRouterProvider",
    "ProviderError",
    "ServerToolBlock",
    "StopReason",
    "TextBlock",
    "ThinkingBlock",
    "Tool",
    "ToolResultBlock",
    "ToolUseBlock",
    "Toolset",
    "TurnUsage",
    "available_models",
    "default_model_ref",
    "deserialize_messages",
    "generator_model_ref",
    "resolve_provider",
    "serialize_messages",
    "split_model_ref",
    "validate_model_ref",
]
