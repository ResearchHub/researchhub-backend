"""Unit tests for the Agent loop, driven by a fake provider (no Django/AWS)."""

from django.test import SimpleTestCase

from research_ai.services.agent.errors import (
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.loop import Agent
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    StopReason,
    TextBlock,
    ToolUseBlock,
    TurnUsage,
)


def _build_text_turn(text, *, stop_reason=StopReason.END_TURN):
    """Build an end-of-turn AssistantTurn carrying a single text block."""
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=stop_reason,
    )


def _build_tool_turn(tool_use_id, name, tool_input):
    """Build an AssistantTurn that requests a single tool call."""
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


class RecorderSpy:
    """Captures recorder callbacks for loop assertions."""

    def __init__(self):
        self.messages = []
        self.turns = []
        self.finished = None
        self.failed = None

    def record_message(self, message, *, turn=None):
        self.messages.append(message)
        self.turns.append(turn)

    def on_run_finished(self, result):
        self.finished = result

    def on_run_failed(self, error):
        self.failed = error


class ExplodingRecorder:
    """Recorder whose failures must not affect agent outcomes."""

    def record_message(self, message, *, turn=None):
        raise ValueError("record failed")

    def on_run_finished(self, result):
        raise ValueError("finish failed")

    def on_run_failed(self, error):
        raise ValueError("fail failed")


def _build_toolset(seen=None):
    """Build a Toolset with search/submit tools that record calls into ``seen``."""
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


def _build_agent(provider, toolset, *, max_iterations=12, recorder=None):
    """Build an Agent wired to the given provider and toolset with fixed defaults."""
    return Agent(
        provider,
        toolset,
        system_prompt="sys",
        max_iterations=max_iterations,
        max_tokens=4096,
        temperature=0.0,
        recorder=recorder,
    )


class AgentLoopTests(SimpleTestCase):
    def test_dispatches_tools_then_stops_on_terminal_tool(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "search", {"q": "jane"}),
                _build_tool_turn("t2", "submit", {"done": True}),
            ]
        )
        seen = []
        agent = _build_agent(provider, _build_toolset(seen))

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
                _build_tool_turn("t1", "search", {"q": "jane"}),
                _build_text_turn("done"),
            ]
        )
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.run("find jane")

        # Assert: the tool result echoes the tool use id (id-correlation).
        tool_result_msg = result.messages[2]
        self.assertEqual(tool_result_msg.role, "user")
        self.assertEqual(tool_result_msg.content[0].tool_use_id, "t1")

    def test_plain_text_turn_ends_loop(self):
        # Arrange
        provider = FakeProvider([_build_text_turn("all done")])
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.run("hi")

        # Assert
        self.assertEqual(result.final_text, "all done")
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.iterations, 1)

    def test_non_terminal_provider_stop_without_tool_calls_raises(self):
        # Arrange: partial text from the provider is not a completed answer.
        provider = FakeProvider(
            [_build_text_turn("partial", stop_reason=StopReason.MAX_TOKENS)]
        )
        agent = _build_agent(provider, _build_toolset())

        # Act / Assert: typed error naming the stop reason, transcript attached.
        with self.assertRaisesRegex(IncompleteTurnError, "max_tokens") as ctx:
            agent.run("hi")
        self.assertEqual(ctx.exception.stop_reason, "max_tokens")
        self.assertEqual(ctx.exception.iterations, 1)
        # The partial assistant turn is on the transcript, not lost.
        self.assertEqual(ctx.exception.messages[-1].role, "assistant")

    def test_exceeding_max_iterations_raises(self):
        # Arrange: the model never stops calling tools.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "search", {}) for i in range(5)]
        )
        agent = _build_agent(provider, _build_toolset(), max_iterations=3)

        # Act / Assert: typed error carrying the cap and the full transcript.
        with self.assertRaises(IterationLimitError) as ctx:
            agent.run("loop forever")
        self.assertEqual(ctx.exception.iterations, 3)
        # user + 3x(assistant turn + tool results) = 7 messages accumulated.
        self.assertEqual(len(ctx.exception.messages), 7)

    def test_provider_exception_is_wrapped_with_transcript(self):
        # Arrange: one good tool turn, then the provider dies mid-run on an
        # exception outside the typed contract.
        class ExplodingProvider(FakeProvider):
            def complete(self, **kwargs):
                if not self._turns:
                    raise ValueError("socket closed")
                return super().complete(**kwargs)

        provider = ExplodingProvider([_build_tool_turn("t1", "search", {})])
        agent = _build_agent(provider, _build_toolset())

        # Act / Assert: wrapped as ProviderError, chained, transcript attached.
        with self.assertRaisesRegex(ProviderError, "socket closed") as ctx:
            agent.run("hi")
        self.assertIsInstance(ctx.exception.__cause__, ValueError)
        self.assertEqual(ctx.exception.iterations, 1)
        # user turn + assistant tool turn + tool results survived the failure.
        self.assertEqual(len(ctx.exception.messages), 3)

    def test_continue_conversation_resumes_from_prefilled_list(self):
        # Arrange: an existing conversation to resume.
        history = [
            Message(role="user", content=[TextBlock(text="earlier")]),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        provider = FakeProvider([_build_text_turn("second answer")])
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.continue_conversation(history, "follow up")

        # Assert: history preserved, the new user turn appended, then driven.
        self.assertEqual(history[-1].content[0].text, "reply")  # not mutated
        self.assertEqual(provider.calls[0][:2], history)
        self.assertEqual(provider.calls[0][2].content[0].text, "follow up")
        self.assertEqual(result.final_text, "second answer")

    def test_recorder_records_appended_messages_and_successful_finish(self):
        # Arrange
        usage = TurnUsage(
            input_tokens=11,
            output_tokens=3,
            cache_read_tokens=7,
            cache_write_tokens=5,
        )
        tool_turn = AssistantTurn(
            text_blocks=[TextBlock(text="searching")],
            tool_calls=[ToolUseBlock(id="t1", name="search", input={"q": "jane"})],
            stop_reason=StopReason.TOOL_USE,
            usage=usage,
            latency_ms=123,
        )
        provider = FakeProvider([tool_turn, _build_text_turn("done")])
        recorder = RecorderSpy()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        result = agent.run("find jane")

        # Assert
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertIs(recorder.finished, result)
        self.assertIsNone(recorder.failed)
        self.assertEqual(
            [m.role for m in recorder.messages],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertIsNone(recorder.turns[0])
        self.assertIs(recorder.turns[1], tool_turn)
        self.assertEqual(recorder.turns[1].usage, usage)
        self.assertEqual(recorder.turns[1].latency_ms, 123)
        self.assertEqual(recorder.messages, result.messages)

    def test_recorder_records_failure_path_messages(self):
        # Arrange: first turn succeeds, second stops incompletely after appending
        # its assistant message.
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "search", {}),
                _build_text_turn("partial", stop_reason=StopReason.MAX_TOKENS),
            ]
        )
        recorder = RecorderSpy()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act / Assert
        with self.assertRaises(IncompleteTurnError) as ctx:
            agent.run("hi")
        self.assertIs(recorder.failed, ctx.exception)
        self.assertIsNone(recorder.finished)
        self.assertEqual(
            [m.role for m in recorder.messages],
            ["user", "assistant", "user", "assistant"],
        )
        self.assertEqual(recorder.messages, ctx.exception.messages)

    def test_raising_recorder_does_not_break_successful_run(self):
        # Arrange
        provider = FakeProvider([_build_text_turn("done")])
        agent = _build_agent(provider, _build_toolset(), recorder=ExplodingRecorder())

        # Act
        result = agent.run("hi")

        # Assert
        self.assertEqual(result.final_text, "done")

    def test_raising_recorder_does_not_mask_run_failure(self):
        # Arrange
        provider = FakeProvider(
            [_build_text_turn("partial", stop_reason=StopReason.MAX_TOKENS)]
        )
        agent = _build_agent(provider, _build_toolset(), recorder=ExplodingRecorder())

        # Act / Assert
        with self.assertRaisesRegex(IncompleteTurnError, "max_tokens"):
            agent.run("hi")
