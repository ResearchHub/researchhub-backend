"""Unit tests for the Agent loop, driven by a fake provider (no Django/AWS)."""

from django.test import SimpleTestCase

from research_ai.services.agent.errors import (
    IncompleteTurnError,
    IterationLimitError,
    ProviderError,
    RepeatedToolFailureError,
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
    ThinkingBlock,
    ToolUseBlock,
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


def _build_agent(
    provider,
    toolset,
    *,
    max_iterations=12,
    max_identical_tool_failures=0,
    recorder=None,
):
    """Build an Agent wired to the given provider and toolset with fixed defaults."""
    return Agent(
        provider,
        toolset,
        system_prompt="sys",
        max_iterations=max_iterations,
        max_tokens=4096,
        temperature=0.0,
        max_identical_tool_failures=max_identical_tool_failures,
        recorder=recorder,
    )


class RecordingRecorder:
    """Captures every recorder hook invocation, in order."""

    def __init__(self):
        self.messages = []  # (message, turn) pairs, in recording order
        self.finished = []
        self.failed = []

    def record_message(self, message, *, turn=None):
        self.messages.append((message, turn))

    def on_run_finished(self, result):
        self.finished.append(result)

    def on_run_failed(self, error):
        self.failed.append(error)


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


def _build_breaker_toolset(flaky_results=None):
    """``search`` succeeds, ``broken`` errs identically, ``flaky`` pops a queue."""
    flaky_results = list(flaky_results or [])
    return Toolset(
        [
            Tool("search", "search", {"type": "object"}, lambda i: {"ok": True}),
            Tool("broken", "broken", {"type": "object"}, lambda i: {"error": "boom"}),
            Tool("flaky", "flaky", {"type": "object"}, lambda i: flaky_results.pop(0)),
        ]
    )


class RepeatedFailureBreakerTests(SimpleTestCase):
    def test_identical_failures_trip_the_breaker(self):
        # Arrange: the same tool fails the same way three turns running.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "broken", {}) for i in range(3)]
        )
        recorder = RecordingRecorder()
        agent = _build_agent(
            provider,
            _build_breaker_toolset(),
            max_identical_tool_failures=3,
            recorder=recorder,
        )

        # Act / Assert
        with self.assertRaisesRegex(RepeatedToolFailureError, "broken.*3 times") as ctx:
            agent.run("go")
        self.assertEqual(ctx.exception.stop_reason, "repeated_tool_failure")
        self.assertEqual(ctx.exception.iterations, 3)
        # The tripping turn's results were recorded before the abort, so the
        # transcript stays resumable.
        self.assertEqual(ctx.exception.messages[-1].role, "user")
        self.assertEqual(recorder.failed, [ctx.exception])

    def test_success_of_the_same_tool_resets_the_streak(self):
        # Arrange: two failures, a success, two more failures -- never three.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "flaky", {}) for i in range(5)]
            + [_build_text_turn("done")]
        )
        flaky = [
            {"error": "x"},
            {"error": "x"},
            {"ok": 1},
            {"error": "x"},
            {"error": "x"},
        ]
        agent = _build_agent(
            provider,
            _build_breaker_toolset(flaky),
            max_identical_tool_failures=3,
        )

        # Act
        result = agent.run("go")

        # Assert
        self.assertEqual(result.final_text, "done")

    def test_different_error_content_resets_the_streak(self):
        # Arrange: the error keeps changing, so the model is getting new signal.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "flaky", {}) for i in range(4)]
            + [_build_text_turn("done")]
        )
        flaky = [{"error": "a"}, {"error": "a"}, {"error": "b"}, {"error": "a"}]
        agent = _build_agent(
            provider,
            _build_breaker_toolset(flaky),
            max_identical_tool_failures=3,
        )

        # Act
        result = agent.run("go")

        # Assert
        self.assertEqual(result.final_text, "done")

    def test_changing_input_with_the_same_error_resets_the_streak(self):
        # Arrange: a constant error text over changing inputs is the model
        # correcting itself, not a stuck loop -- it must not be aborted.
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "broken", {"attempt": i}) for i in range(4)]
            + [_build_text_turn("done")]
        )
        agent = _build_agent(
            provider,
            _build_breaker_toolset(),
            max_identical_tool_failures=3,
        )

        # Act
        result = agent.run("go")

        # Assert
        self.assertEqual(result.final_text, "done")

    def test_another_tools_success_does_not_reset_the_streak(self):
        # Arrange: the incident shape -- reads succeed between identical edit
        # failures, and the run is still stuck.
        provider = FakeProvider(
            [
                _build_tool_turn("t1", "broken", {}),
                _build_tool_turn("t2", "search", {}),
                _build_tool_turn("t3", "broken", {}),
                _build_tool_turn("t4", "search", {}),
                _build_tool_turn("t5", "broken", {}),
            ]
        )
        agent = _build_agent(
            provider,
            _build_breaker_toolset(),
            max_identical_tool_failures=3,
        )

        # Act / Assert
        with self.assertRaises(RepeatedToolFailureError) as ctx:
            agent.run("go")
        self.assertEqual(ctx.exception.iterations, 5)

    def test_parallel_identical_failures_count_once_per_turn(self):
        # Arrange: one turn fanning out two identical failing calls is one
        # strike, not two.
        def fan_out(i):
            return AssistantTurn(
                text_blocks=[],
                tool_calls=[
                    ToolUseBlock(id=f"a{i}", name="broken", input={}),
                    ToolUseBlock(id=f"b{i}", name="broken", input={}),
                ],
                stop_reason=StopReason.TOOL_USE,
            )

        completes = FakeProvider([fan_out(1), _build_text_turn("done")])
        agent = _build_agent(
            completes, _build_breaker_toolset(), max_identical_tool_failures=2
        )
        self.assertEqual(agent.run("go").final_text, "done")

        # Act / Assert: the second identical turn is the second strike.
        trips = FakeProvider([fan_out(1), fan_out(2)])
        agent = _build_agent(
            trips, _build_breaker_toolset(), max_identical_tool_failures=2
        )
        with self.assertRaises(RepeatedToolFailureError) as ctx:
            agent.run("go")
        self.assertEqual(ctx.exception.iterations, 2)

    def test_zero_disables_the_breaker(self):
        # Arrange
        provider = FakeProvider(
            [_build_tool_turn(f"t{i}", "broken", {}) for i in range(4)]
        )
        agent = _build_agent(
            provider,
            _build_breaker_toolset(),
            max_iterations=3,
            max_identical_tool_failures=0,
        )

        # Act / Assert: only the iteration cap bounds the run.
        with self.assertRaises(IterationLimitError):
            agent.run("go")

    def test_repeated_truncations_trip_the_breaker(self):
        # Arrange: the synthesized truncation error is deterministic per tool,
        # so a model re-emitting the same oversized call burns out quickly --
        # even though each cut input differs, since a truncated input carries
        # no new intent and is excluded from the failure identity.
        provider = FakeProvider(
            [
                _build_tool_turn(
                    f"t{i}", "search", {"cut": i}, stop_reason=StopReason.MAX_TOKENS
                )
                for i in range(3)
            ]
        )
        agent = _build_agent(provider, _build_toolset(), max_identical_tool_failures=3)

        # Act / Assert
        with self.assertRaises(RepeatedToolFailureError) as ctx:
            agent.run("go")
        self.assertEqual(ctx.exception.iterations, 3)

    def test_terminal_tool_success_wins_over_the_breaker(self):
        # Arrange: the tripping turn also completed the run via a terminal
        # tool; the finished result must win over the abort.
        turn = AssistantTurn(
            text_blocks=[],
            tool_calls=[
                ToolUseBlock(id="t1", name="broken", input={}),
                ToolUseBlock(id="t2", name="submit", input={}),
            ],
            stop_reason=StopReason.TOOL_USE,
        )
        provider = FakeProvider([turn])

        def submit(input):
            return {"received": True}

        toolset = Toolset(
            [
                Tool(
                    "broken", "broken", {"type": "object"}, lambda i: {"error": "boom"}
                ),
                Tool("submit", "submit", {"type": "object"}, submit, is_terminal=True),
            ]
        )
        agent = _build_agent(provider, toolset, max_identical_tool_failures=1)

        # Act
        result = agent.run("go")

        # Assert
        self.assertEqual(result.stop_reason, "stop_tool")


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
