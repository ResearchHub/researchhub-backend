"""Unit tests for the Agent loop, driven by a fake provider (no Django/AWS)."""

from django.test import SimpleTestCase

from research_ai.services.agent.errors import (
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
)
from research_ai.services.agent.loop import Agent, _summarize_server_result
from research_ai.services.agent.providers.base import LLMProvider
from research_ai.services.agent.tools import Tool, Toolset
from research_ai.services.agent.types import (
    AssistantTurn,
    Message,
    ServerToolBlock,
    StopReason,
    TextBlock,
    TextStreamDelta,
    ThinkingBlock,
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


def _build_tool_turn(tool_use_id, name, tool_input, *, stop_reason=StopReason.TOOL_USE):
    """Build an AssistantTurn that requests a single tool call."""
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[ToolUseBlock(id=tool_use_id, name=name, input=tool_input)],
        stop_reason=stop_reason,
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


class RecordingRecorder:
    """Captures every recorder hook invocation, in order."""

    def __init__(self):
        self.messages = []  # (message, turn) pairs, in recording order
        self.finished = []
        self.failed = []
        self.usages = []
        self.stream_events = []
        self.stream_flushes = 0

    def record_usage(self, usage):
        self.usages.append(usage)

    def record_message(self, message, *, turn=None):
        self.messages.append((message, turn))

    def on_run_finished(self, result):
        self.finished.append(result)

    def on_run_failed(self, error):
        self.failed.append(error)

    def record_stream_event(self, iteration, event):
        self.stream_events.append((iteration, event))

    def flush_stream_events(self):
        self.stream_flushes += 1


class RaisingRecorder:
    """Every hook raises, to prove recording failures never break the run."""

    def record_message(self, message, *, turn=None):
        raise OSError("db gone")

    def on_run_finished(self, result):
        raise OSError("db gone")

    def on_run_failed(self, error):
        raise OSError("db gone")


class ServerResultSummaryTests(SimpleTestCase):
    def test_encrypted_execution_success_logs_only_structural_metadata(self):
        # Arrange
        content = {
            "type": "encrypted_code_execution_result",
            "encrypted_stdout": "opaque-secret",
            "return_code": 0,
            "stderr": "",
            "content": [],
        }

        # Act
        summary = _summarize_server_result(content)

        # Assert
        self.assertEqual(
            summary,
            "encrypted_code_execution_result (return_code=0, outputs=0)",
        )
        self.assertNotIn("opaque-secret", summary)

    def test_server_tool_error_logs_its_error_code(self):
        # Arrange
        content = {
            "type": "code_execution_tool_result_error",
            "error_code": "execution_time_exceeded",
        }

        # Act
        summary = _summarize_server_result(content)

        # Assert
        self.assertEqual(summary, "error: execution_time_exceeded")

    def test_search_result_list_logs_only_its_size(self):
        # Arrange
        content = [{"url": "https://example.org/private-result"}]

        # Act
        summary = _summarize_server_result(content)

        # Assert
        self.assertEqual(summary, "[1 results]")
        self.assertNotIn("private-result", summary)


class AgentLoopTests(SimpleTestCase):
    def test_provider_usage_reaches_recorder_before_provider_failure(self):
        # Arrange: a provider received a billable response but rejected it
        # before it could return an AssistantTurn to the loop.
        usage = TurnUsage(input_tokens=10, output_tokens=3)

        class RespondingThenFailingProvider(FakeProvider):
            def complete(self, *, on_usage, **kwargs):
                on_usage(usage)
                raise ProviderError("response could not be replayed")

        recorder = RecordingRecorder()
        agent = _build_agent(
            RespondingThenFailingProvider([]),
            _build_toolset(),
            recorder=recorder,
        )

        # Act
        with self.assertRaises(ProviderError):
            agent.run("research")

        # Assert
        self.assertEqual(recorder.usages, [usage])
        self.assertEqual(recorder.messages[0][0].role, "user")
        self.assertEqual(len(recorder.messages), 1)

    def test_provider_retry_rechecks_execution_activity(self):
        # Arrange: the run is active before its first provider request, then is
        # cancelled while that request is in flight.
        class CancellingRecorder(RecordingRecorder):
            def __init__(self):
                super().__init__()
                self.activity_checks = 0

            def is_active(self):
                self.activity_checks += 1
                return self.activity_checks == 1

        class InternallyRetryingProvider(FakeProvider):
            def __init__(self):
                super().__init__([_build_text_turn("unreached")])
                self.requests = 0

            def complete(self, *, before_retry, **kwargs):
                self.requests += 1
                before_retry()
                self.requests += 1
                return super().complete(**kwargs)

        recorder = CancellingRecorder()
        provider = InternallyRetryingProvider()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        with self.assertRaises(InterruptedError):
            agent.run("research")

        # Assert
        self.assertEqual(provider.requests, 1)
        self.assertEqual(recorder.activity_checks, 2)

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

    def test_thinking_blocks_lead_the_replayed_assistant_turn(self):
        # Arrange: a turn that thinks, narrates, then calls a tool.
        thinking = ThinkingBlock(data={"type": "thinking", "signature": "sig"})
        provider = FakeProvider(
            [
                AssistantTurn(
                    text_blocks=[TextBlock(text="searching")],
                    thinking_blocks=[thinking],
                    tool_calls=[
                        ToolUseBlock(id="t1", name="search", input={"q": "jane"})
                    ],
                    stop_reason=StopReason.TOOL_USE,
                ),
                _build_text_turn("done"),
            ]
        )
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.run("find jane")

        # Assert: the signed reasoning block is replayed first, intact.
        assistant_message = result.messages[1]
        self.assertEqual(assistant_message.content[0], thinking)
        self.assertIsInstance(assistant_message.content[1], TextBlock)
        self.assertIsInstance(assistant_message.content[2], ToolUseBlock)

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

    def test_recorder_sees_every_message_and_the_finish(self):
        # Arrange: a tool turn then a plain-text answer.
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "search", {"q": "jane"}),
                _build_text_turn("done"),
            ]
        )
        recorder = RecordingRecorder()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        result = agent.run("find jane")

        # Assert: the recorded messages are exactly the run's transcript, in order.
        self.assertEqual([m for m, _ in recorder.messages], result.messages)
        # Assistant rows carry their turn (usage/latency ride along); others don't.
        turns_by_role = [(m.role, turn is not None) for m, turn in recorder.messages]
        self.assertEqual(
            turns_by_role,
            [
                ("user", False),
                ("assistant", True),
                ("user", False),
                ("assistant", True),
            ],
        )
        self.assertEqual(recorder.finished, [result])
        self.assertEqual(recorder.failed, [])

    def test_provider_stream_events_reach_recorder_and_flush_before_turn(self):
        # Arrange
        delta = TextStreamDelta(block_index=0, text="hel")

        class StreamingProvider(FakeProvider):
            def complete_with_events(self, *, on_event, **kwargs):
                on_event(delta)
                return self.complete(**kwargs)

        recorder = RecordingRecorder()
        agent = _build_agent(
            StreamingProvider([_build_text_turn("hello")]),
            _build_toolset(),
            recorder=recorder,
        )

        # Act
        agent.run("hi")

        # Assert
        self.assertEqual(recorder.stream_events, [(1, delta)])
        self.assertEqual(recorder.stream_flushes, 1)

    def test_recorder_sees_failure_with_all_prior_messages(self):
        # Arrange: one good tool turn, then the provider dies.
        class ExplodingProvider(FakeProvider):
            def complete(self, **kwargs):
                if not self._turns:
                    raise ValueError("socket closed")
                return super().complete(**kwargs)

        provider = ExplodingProvider([_build_tool_turn("t1", "search", {})])
        recorder = RecordingRecorder()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        with self.assertRaises(ProviderError) as ctx:
            agent.run("hi")

        # Assert: every message up to the failure was recorded, then the failure.
        self.assertEqual([m for m, _ in recorder.messages], ctx.exception.messages)
        self.assertEqual(len(recorder.messages), 3)  # user, assistant, tool results
        self.assertEqual(recorder.failed, [ctx.exception])
        self.assertEqual(recorder.finished, [])

    def test_recorder_sees_iteration_limit_failure(self):
        # Arrange: the model never stops calling tools.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "search", {}) for i in range(5)]
        )
        recorder = RecordingRecorder()
        agent = _build_agent(
            provider, _build_toolset(), max_iterations=2, recorder=recorder
        )

        # Act
        with self.assertRaises(IterationLimitError) as ctx:
            agent.run("loop forever")

        # Assert: the full accumulated transcript was recorded before the failure.
        self.assertEqual([m for m, _ in recorder.messages], ctx.exception.messages)
        self.assertEqual(recorder.failed, [ctx.exception])

    def test_raising_recorder_does_not_break_the_run(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "search", {"q": "jane"}),
                _build_text_turn("all done"),
            ]
        )
        agent = _build_agent(provider, _build_toolset(), recorder=RaisingRecorder())

        # Act: every hook raises; the run must still complete normally.
        result = agent.run("find jane")

        # Assert
        self.assertEqual(result.final_text, "all done")
        self.assertEqual(result.stop_reason, "end_turn")

    def test_raising_recorder_does_not_mask_run_failure(self):
        # Arrange: the run itself fails AND the recorder raises on the hook.
        provider = FakeProvider(
            [_build_text_turn("partial", stop_reason=StopReason.MAX_TOKENS)]
        )
        agent = _build_agent(provider, _build_toolset(), recorder=RaisingRecorder())

        # Act / Assert: the run's own typed error propagates, not the recorder's.
        with self.assertRaises(IncompleteTurnError):
            agent.run("hi")

    def test_continue_conversation_records_only_the_appended_turn(self):
        # Arrange: prior history is already persisted; recording it again would
        # duplicate rows.
        history = [
            Message(role="user", content=[TextBlock(text="earlier")]),
            Message(role="assistant", content=[TextBlock(text="reply")]),
        ]
        provider = FakeProvider([_build_text_turn("second answer")])
        recorder = RecordingRecorder()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        agent.continue_conversation(history, "follow up")

        # Assert: the new user turn and the new assistant turn -- not the history.
        recorded_texts = [m.content[0].text for m, _ in recorder.messages]
        self.assertEqual(recorded_texts, ["follow up", "second answer"])

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


class TruncatedTurnTests(SimpleTestCase):
    """Turns cut off on max_tokens while requesting tools are not dispatched."""

    def test_truncated_tool_turn_is_answered_not_dispatched(self):
        # Arrange: the provider truncates mid-call, then completes normally.
        provider = FakeProvider(
            [
                _build_tool_turn(
                    "t1", "search", {"q": "par"}, stop_reason=StopReason.MAX_TOKENS
                ),
                _build_text_turn("done"),
            ]
        )
        seen = []
        agent = _build_agent(provider, _build_toolset(seen))

        # Act
        result = agent.run("find jane")

        # Assert: the handler never ran; the model got the real cause instead.
        self.assertEqual(seen, [])
        self.assertEqual(result.final_text, "done")
        self.assertEqual(result.iterations, 2)
        synthesized = provider.calls[1][-1]
        self.assertEqual(synthesized.role, "user")
        block = synthesized.content[0]
        self.assertEqual(block.tool_use_id, "t1")
        self.assertTrue(block.is_error)
        self.assertIn("truncated", block.content["error"])
        self.assertIn("search", block.content["error"])

    def test_truncated_turn_synthesizes_a_result_for_every_call(self):
        # Arrange: two calls in the cut-off turn, one of them a terminal tool.
        truncated = AssistantTurn(
            text_blocks=[],
            tool_calls=[
                ToolUseBlock(id="t1", name="search", input={}),
                ToolUseBlock(id="t2", name="submit", input={}),
            ],
            stop_reason=StopReason.MAX_TOKENS,
        )
        provider = FakeProvider([truncated, _build_text_turn("done")])
        seen = []
        agent = _build_agent(provider, _build_toolset(seen))

        # Act
        result = agent.run("go")

        # Assert: every call is answered (the API requires a result per call),
        # and the unexecuted terminal tool does not end the run.
        self.assertEqual(seen, [])
        synthesized = provider.calls[1][-1]
        self.assertEqual([b.tool_use_id for b in synthesized.content], ["t1", "t2"])
        self.assertTrue(all(b.is_error for b in synthesized.content))
        self.assertEqual(result.stop_reason, "end_turn")

    def test_truncated_turn_results_are_recorded(self):
        # Arrange
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "search", {}, stop_reason=StopReason.MAX_TOKENS),
                _build_text_turn("done"),
            ]
        )
        recorder = RecordingRecorder()
        agent = _build_agent(provider, _build_toolset(), recorder=recorder)

        # Act
        result = agent.run("go")

        # Assert: the synthesized results are on the durable transcript.
        self.assertEqual([m for m, _ in recorder.messages], result.messages)
        roles = [m.role for m, _ in recorder.messages]
        self.assertEqual(roles, ["user", "assistant", "user", "assistant"])


def _build_server_search_turn(*, stop_reason=StopReason.PAUSE_TURN):
    """A turn whose whole content is a provider-run search and its result."""
    return AssistantTurn(
        text_blocks=[],
        tool_calls=[],
        stop_reason=stop_reason,
        content_blocks=[
            ServerToolBlock(
                data={
                    "type": "server_tool_use",
                    "id": "s1",
                    "name": "web_search",
                    "input": {"query": "llipta ash"},
                }
            ),
            ServerToolBlock(
                data={
                    "type": "web_search_tool_result",
                    "tool_use_id": "s1",
                    "content": [{"url": "https://example.org/llipta"}],
                }
            ),
        ],
    )


class ServerSideToolTests(SimpleTestCase):
    """Turns the provider ran tools inside, which the loop only carries."""

    def test_paused_turn_resumes_with_no_user_turn_appended(self):
        # Arrange: the provider pauses after its per-turn search budget, then
        # finishes on the next call.
        provider = FakeProvider(
            [_build_server_search_turn(), _build_text_turn("all done")]
        )
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.run("go")

        # Assert: the run continued rather than dying on an incomplete turn,
        # and the resuming request ends with the paused assistant turn -- a
        # user turn there would be answering a question nobody asked.
        self.assertEqual(result.final_text, "all done")
        self.assertEqual(result.stop_reason, "end_turn")
        self.assertEqual(result.iterations, 2)
        resumed = provider.calls[1]
        self.assertEqual(resumed[-1].role, "assistant")
        self.assertTrue(
            all(isinstance(b, ServerToolBlock) for b in resumed[-1].content)
        )

    def test_paused_turn_carries_provider_state_into_resuming_request(self):
        # Arrange: request-level continuation state accompanies a server-side
        # turn but is not itself a content block.
        paused = _build_server_search_turn()
        paused = AssistantTurn(
            text_blocks=paused.text_blocks,
            tool_calls=paused.tool_calls,
            stop_reason=paused.stop_reason,
            content_blocks=paused.content_blocks,
            provider_state={
                "anthropic": {"container": {"id": "container_123"}},
            },
        )
        provider = FakeProvider([paused, _build_text_turn("all done")])
        agent = _build_agent(provider, _build_toolset())

        # Act
        agent.run("go")

        # Assert
        self.assertEqual(
            provider.calls[1][-1].provider_state,
            {"anthropic": {"container": {"id": "container_123"}}},
        )

    def test_paused_turn_still_counts_against_the_iteration_cap(self):
        # Arrange: a provider that never stops pausing.
        provider = FakeProvider([_build_server_search_turn() for _ in range(4)])
        agent = _build_agent(provider, _build_toolset(), max_iterations=3)

        # Act / Assert: bounded by the cap rather than looping forever.
        with self.assertRaises(IterationLimitError):
            agent.run("go")
        self.assertEqual(len(provider.calls), 3)

    def test_turn_is_replayed_in_the_providers_own_order(self):
        # Arrange: text sits *between* the search and a tool call, which the
        # old grouped ordering would have hoisted to the front.
        turn = _build_server_search_turn(stop_reason=StopReason.TOOL_USE)
        ordered = [
            *turn.content_blocks,
            TextBlock(text="now I will search the index"),
            ToolUseBlock(id="t1", name="search", input={"q": 1}),
        ]
        provider = FakeProvider(
            [
                AssistantTurn(
                    text_blocks=[TextBlock(text="now I will search the index")],
                    tool_calls=[ToolUseBlock(id="t1", name="search", input={"q": 1})],
                    stop_reason=StopReason.TOOL_USE,
                    content_blocks=ordered,
                ),
                _build_text_turn("done"),
            ]
        )
        agent = _build_agent(provider, _build_toolset())

        # Act
        result = agent.run("go")

        # Assert: the assistant turn went back exactly as the provider sent it.
        assistant = result.messages[1]
        self.assertEqual(assistant.content, ordered)
