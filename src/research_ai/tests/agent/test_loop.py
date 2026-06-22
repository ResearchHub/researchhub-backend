"""Unit tests for the Agent loop, driven by a fake provider (no Django/AWS)."""

from django.test import SimpleTestCase

from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolUseBlock,
)


def _text_turn(text):
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=StopReason.END_TURN,
    )


def _tool_turn(tool_use_id, name, tool_input):
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[ToolUseBlock(id=tool_use_id, name=name, input=tool_input)],
        stop_reason=StopReason.TOOL_USE,
    )


class FakeProvider(LLMProvider):
    """Returns queued ``AssistantTurn``s; records the messages it was sent."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    def render_tools(self, tools):
        return {"rendered": [t.name for t in tools]}

    def complete(self, *, system_prompt, messages, rendered_tools, **kwargs):
        # Snapshot the message count; the loop keeps appending to the list.
        self.calls.append(list(messages))
        return self._turns.pop(0)


def _toolset(seen=None):
    seen = seen if seen is not None else []

    def search(input):
        seen.append(("search", input))
        return {"ok": True}

    def submit(input):
        seen.append(("submit", input))
        return {"received": True}

    return Toolset(
        [
            Tool("search", "search", {"type": "object"}, search),
            Tool("submit", "submit", {"type": "object"}, submit, is_terminal=True),
        ]
    )


def _agent(provider, toolset, *, max_iterations=12):
    return Agent(
        provider,
        toolset,
        system_prompt="sys",
        max_iterations=max_iterations,
        max_tokens=4096,
        temperature=0.0,
    )


class AgentLoopTests(SimpleTestCase):
    def test_dispatches_tools_then_stops_on_terminal_tool(self):
        # Arrange
        provider = FakeProvider(
            [
                _tool_turn("t1", "search", {"q": "jane"}),
                _tool_turn("t2", "submit", {"done": True}),
            ]
        )
        seen = []
        agent = _agent(provider, _toolset(seen))

        # Act
        result = agent.run("find jane")

        # Assert: both tools ran; the run stopped on the terminal tool.
        self.assertEqual(seen, [("search", {"q": "jane"}), ("submit", {"done": True})])
        self.assertEqual(result.stop_reason, "stop_tool")
        self.assertEqual(result.iterations, 2)

    def test_tool_use_and_result_ids_correlate(self):
        # Arrange
        provider = FakeProvider(
            [
                _tool_turn("t1", "search", {"q": "jane"}),
                _text_turn("done"),
            ]
        )
        agent = _agent(provider, _toolset())

        # Act
        result = agent.run("find jane")

        # Assert: the tool result echoes the tool use id (id-correlation).
        tool_result_msg = result.messages[2]
        self.assertEqual(tool_result_msg.role, "user")
        self.assertEqual(tool_result_msg.content[0].tool_use_id, "t1")

    def test_plain_text_turn_ends_loop(self):
        # Arrange
        provider = FakeProvider([_text_turn("all done")])
        agent = _agent(provider, _toolset())

        # Act
        result = agent.run("hi")

        # Assert
        self.assertEqual(result.final_text, "all done")
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.iterations, 1)

    def test_exceeding_max_iterations_raises(self):
        # Arrange: the model never stops calling tools.
        provider = FakeProvider([_tool_turn(f"t{i}", "search", {}) for i in range(5)])
        agent = _agent(provider, _toolset(), max_iterations=3)

        # Act / Assert
        with self.assertRaises(RuntimeError):
            agent.run("loop forever")

    def test_continue_conversation_resumes_from_prefilled_list(self):
        # Arrange: an existing conversation to resume.
        history = [
            Message(role="user", content=[TextBlock(text="earlier")]),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        provider = FakeProvider([_text_turn("second answer")])
        agent = _agent(provider, _toolset())

        # Act
        result = agent.continue_conversation(history, "follow up")

        # Assert: history preserved, the new user turn appended, then driven.
        self.assertEqual(history[-1].content[0].text, "reply")  # not mutated
        self.assertEqual(provider.calls[0][:2], history)
        self.assertEqual(provider.calls[0][2].content[0].text, "follow up")
        self.assertEqual(result.final_text, "second answer")
