"""Shared fakes and builders for agent-persistence tests."""

from django.test import TestCase

from research_ai.models import AgentConversation
from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    StopReason,
    TextBlock,
    ToolUseBlock,
)
from research_ai.services.agent_persistence import AgentExecutionService


class FakeProvider(LLMProvider):
    def __init__(self, turns, *, render_error=None):
        self.turns = list(turns)
        self.render_error = render_error
        self.calls = []

    def render_tools(self, tools):
        if self.render_error:
            raise self.render_error
        return [tool.name for tool in tools]

    def complete(self, **kwargs):
        self.calls.append(list(kwargs["messages"]))
        turn = self.turns.pop(0)
        if isinstance(turn, BaseException):
            raise turn
        return turn


def tool_turn(
    call_id,
    name,
    tool_input,
    *,
    stop_reason=StopReason.TOOL_USE,
    usage=None,
    latency_ms=None,
):
    return AssistantTurn(
        text_blocks=[TextBlock(text=f"calling {name}")],
        tool_calls=[ToolUseBlock(id=call_id, name=name, input=tool_input)],
        stop_reason=stop_reason,
        usage=usage,
        latency_ms=latency_ms,
    )


def text_turn(text, *, usage=None, latency_ms=None, provider_state=None):
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=StopReason.END_TURN,
        usage=usage,
        latency_ms=latency_ms,
        provider_state=provider_state or {},
    )


def agent(provider, recorder, tools=None, *, max_identical_tool_failures=0):
    return Agent(
        provider,
        Toolset(tools or []),
        system_prompt="internal system scaffolding",
        max_iterations=5,
        max_tokens=2048,
        temperature=0.1,
        max_identical_tool_failures=max_identical_tool_failures,
        recorder=recorder,
    )


class AgentPersistenceTestCase(TestCase):
    def setUp(self):
        self.conversation = AgentConversation.objects.create(
            workflow="notebook_chat",
        )

    def recorder(self, **kwargs):
        return AgentExecutionService().start(
            self.conversation,
            provider="fake",
            model="fake-model-v1",
            configuration={"max_tokens": 2048, "temperature": 0.1},
            **kwargs,
        )
