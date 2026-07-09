"""Tests for ``DatabaseAgentRecorder`` and ``build_context``.

A real ``Agent`` loop is driven by a fake provider against a real database
recorder, so what is asserted is the persisted transcript of an actual run --
not the recorder's methods in isolation.
"""

from django.test import TestCase

from research_ai.models import AgentConversation, AgentRun
from research_ai.services.agent import (
    Agent,
    AssistantTurn,
    IncompleteTurnError,
    Message,
    ProviderError,
    StopReason,
    TextBlock,
    Tool,
    ToolResultBlock,
    Toolset,
    ToolUseBlock,
    TurnUsage,
    serialize_messages,
)
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent_transcript import DatabaseAgentRecorder, build_context


class FakeProvider(LLMProvider):
    """Returns queued ``AssistantTurn``s."""

    def __init__(self, turns):
        self._turns = list(turns)

    def render_tools(self, tools):
        return {"rendered": [t.name for t in tools]}

    def complete(self, **kwargs):
        return self._turns.pop(0)


class ExplodingProvider(FakeProvider):
    """Plays its queued turns, then dies outside the typed contract."""

    def complete(self, **kwargs):
        if not self._turns:
            raise ValueError("socket closed")
        return super().complete(**kwargs)


def _build_text_turn(text, *, usage=None, latency_ms=None, stop_reason=None):
    """Build an end-of-turn AssistantTurn carrying a single text block."""
    return AssistantTurn(
        text_blocks=[TextBlock(text=text)],
        tool_calls=[],
        stop_reason=stop_reason or StopReason.END_TURN,
        usage=usage,
        latency_ms=latency_ms,
    )


def _build_tool_turn(tool_use_id, tool_input=None, *, usage=None, latency_ms=None):
    """Build an AssistantTurn that requests a single ``search`` call."""
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[
            ToolUseBlock(id=tool_use_id, name="search", input=tool_input or {"q": "x"})
        ],
        stop_reason=StopReason.TOOL_USE,
        usage=usage,
        latency_ms=latency_ms,
    )


def _build_toolset(search=None):
    """Build a Toolset with a single ``search`` tool."""
    return Toolset(
        [Tool("search", "search", {"type": "object"}, search or (lambda i: {"ok": 1}))]
    )


def _build_agent(provider, *, recorder, toolset=None):
    """Build an Agent wired to the given provider and recorder."""
    return Agent(
        provider,
        toolset or _build_toolset(),
        system_prompt="sys",
        max_iterations=12,
        max_tokens=4096,
        temperature=0.0,
        recorder=recorder,
    )


def _make_conversation(**kwargs):
    """Persist an AgentConversation (headless: no created_by)."""
    kwargs.setdefault("kind", AgentConversation.Kind.PROPOSAL_DRAFT)
    kwargs.setdefault("system_prompt", "sys")
    return AgentConversation.objects.create(**kwargs)


class DatabaseAgentRecorderTests(TestCase):
    def test_full_run_persists_the_transcript_and_finalizes_the_run(self):
        # Arrange: a tool turn then a plain-text answer, both reporting usage.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(
            conversation, model_id="test-model", config={"max_iterations": 12}
        )
        provider = FakeProvider(
            [
                _build_tool_turn(
                    "t1",
                    usage=TurnUsage(
                        input_tokens=10,
                        output_tokens=2,
                        cache_read_tokens=5,
                        cache_write_tokens=1,
                    ),
                    latency_ms=100,
                ),
                _build_text_turn(
                    "done",
                    usage=TurnUsage(input_tokens=7, output_tokens=3),
                    latency_ms=50,
                ),
            ]
        )
        agent = _build_agent(provider, recorder=recorder)

        # Act
        result = agent.run("find jane")

        # Assert: the stored rows are exactly the run's transcript, in order.
        rows = list(conversation.messages.order_by("sequence"))
        self.assertEqual([r.sequence for r in rows], [0, 1, 2, 3])
        self.assertEqual(
            [{"role": r.role, "content": r.content} for r in rows],
            serialize_messages(result.messages),
        )
        # Assistant rows carry the per-turn metadata; user rows carry none.
        assistant_first = rows[1]
        self.assertEqual(assistant_first.input_tokens, 10)
        self.assertEqual(assistant_first.output_tokens, 2)
        self.assertEqual(assistant_first.cache_read_tokens, 5)
        self.assertEqual(assistant_first.cache_write_tokens, 1)
        self.assertEqual(assistant_first.latency_ms, 100)
        self.assertEqual(assistant_first.stop_reason, "tool_use")
        self.assertEqual(rows[3].stop_reason, "end_turn")
        # Unreported counters stay None, distinct from a reported zero.
        self.assertIsNone(rows[3].cache_read_tokens)
        self.assertIsNone(rows[0].input_tokens)
        self.assertEqual(rows[0].stop_reason, "")
        # The run row is finalized with summed aggregates.
        run = recorder.run
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.COMPLETED)
        self.assertEqual(run.stop_reason, "end_turn")
        self.assertEqual(run.iterations, 2)
        self.assertEqual(run.model_id, "test-model")
        self.assertEqual(run.config, {"max_iterations": 12})
        self.assertEqual(run.input_tokens, 17)
        self.assertEqual(run.output_tokens, 5)
        self.assertEqual(run.cache_read_tokens, 5)
        self.assertEqual(run.cache_write_tokens, 1)
        self.assertIsNotNone(run.finished_at)
        self.assertIsNotNone(run.duration)
        self.assertEqual(run.error_message, "")

    def test_build_context_round_trips_the_transcript(self):
        # Arrange: persist a full run.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        provider = FakeProvider([_build_tool_turn("t1"), _build_text_turn("done")])
        agent = _build_agent(provider, recorder=recorder)

        # Act
        result = agent.run("find jane")

        # Assert: the derived context is the run's exact message list.
        self.assertEqual(build_context(conversation), result.messages)

    def test_mid_run_provider_error_leaves_failed_run_with_all_messages(self):
        # Arrange: one good tool turn, then the provider dies.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        provider = ExplodingProvider([_build_tool_turn("t1")])
        agent = _build_agent(provider, recorder=recorder)

        # Act
        with self.assertRaises(ProviderError) as ctx:
            agent.run("hi")

        # Assert: every message up to the failure is persisted.
        rows = list(conversation.messages.order_by("sequence"))
        self.assertEqual(
            [{"role": r.role, "content": r.content} for r in rows],
            serialize_messages(ctx.exception.messages),
        )
        self.assertEqual(len(rows), 3)  # user, assistant, tool results
        run = recorder.run
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertIn("socket closed", run.error_message)
        self.assertEqual(run.iterations, 1)
        self.assertIsNotNone(run.finished_at)

    def test_incomplete_turn_failure_records_its_stop_reason(self):
        # Arrange: the provider truncates without answering or calling a tool.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        provider = FakeProvider(
            [_build_text_turn("partial", stop_reason=StopReason.MAX_TOKENS)]
        )
        agent = _build_agent(provider, recorder=recorder)

        # Act
        with self.assertRaises(IncompleteTurnError):
            agent.run("hi")

        # Assert: the failed run carries the provider's stop reason.
        run = recorder.run
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertEqual(run.stop_reason, "max_tokens")

    def test_oversized_block_strings_are_capped_with_a_marker(self):
        # Arrange: a tool result nesting a string far over the cap.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation, max_block_chars=20)

        # Act
        recorder.record_message(
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="t1",
                        content={"pdf": {"text": "x" * 500}, "pages": 3},
                    )
                ],
            )
        )

        # Assert: the nested string is capped and the block marked truncated.
        block = conversation.messages.get().content[0]
        self.assertEqual(block["content"]["pdf"]["text"], "x" * 20)
        self.assertEqual(block["content"]["pages"], 3)
        self.assertIs(block["truncated"], True)

    def test_under_cap_blocks_are_stored_verbatim_without_marker(self):
        # Arrange
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation, max_block_chars=20)

        # Act
        recorder.record_message(Message(role="user", content=[TextBlock(text="short")]))

        # Assert
        block = conversation.messages.get().content[0]
        self.assertEqual(block, {"type": "text", "text": "short"})
        self.assertNotIn("truncated", block)

    def test_second_run_on_a_conversation_continues_the_sequence(self):
        # Arrange: a first recorded run on the conversation.
        conversation = _make_conversation()
        first = DatabaseAgentRecorder(conversation)
        provider = FakeProvider([_build_text_turn("first answer")])
        _build_agent(provider, recorder=first).run("hi")

        # Act: a second run appends to the same conversation's log.
        second = DatabaseAgentRecorder(conversation)
        history = build_context(conversation)
        provider = FakeProvider([_build_text_turn("second answer")])
        _build_agent(provider, recorder=second).continue_conversation(
            history, "follow up"
        )

        # Assert: one unbroken sequence across two runs, no duplicated history.
        rows = list(conversation.messages.order_by("sequence"))
        self.assertEqual([r.sequence for r in rows], [0, 1, 2, 3])
        self.assertEqual([r.run_id for r in rows[:2]], [first.run.id] * 2)
        self.assertEqual([r.run_id for r in rows[2:]], [second.run.id] * 2)
        self.assertEqual(rows[2].content[0]["text"], "follow up")
        self.assertEqual(AgentRun.objects.filter(conversation=conversation).count(), 2)

    def test_run_aggregates_update_as_turns_land(self):
        # Arrange: record an assistant turn directly, with no terminal hook --
        # an in-flight (or crashed) run must already show its cost.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)

        # Act
        recorder.record_message(
            Message(role="assistant", content=[TextBlock(text="thinking")]),
            turn=_build_text_turn(
                "thinking", usage=TurnUsage(input_tokens=9, output_tokens=4)
            ),
        )

        # Assert
        run = AgentRun.objects.get(id=recorder.run.id)
        self.assertEqual(run.status, AgentRun.Status.RUNNING)
        self.assertEqual(run.iterations, 1)
        self.assertEqual(run.input_tokens, 9)
        self.assertEqual(run.output_tokens, 4)
