"""Tests for ``DatabaseAgentRecorder`` and ``build_context``.

A real ``Agent`` loop is driven by a fake provider against a real database
recorder, so what is asserted is the persisted transcript of an actual run --
not the recorder's methods in isolation.
"""

from django.db import DataError, transaction
from django.test import TestCase

from research_ai.models import (
    AgentChatMessage,
    AgentConversation,
    AgentRun,
    AgentTranscriptEntry,
)
from research_ai.services.agent import (
    Agent,
    AgentResult,
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
from research_ai.services.agent_transcript import (
    DatabaseAgentRecorder,
    build_chat_view,
    build_context,
)


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


class ExplodingRenderProvider(FakeProvider):
    """Fails while preparing tools, before the first model turn."""

    def render_tools(self, tools):
        raise ValueError("tool rendering exploded")


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
    def test_accepts_the_full_bedrock_model_id_length(self):
        # Arrange
        conversation = _make_conversation()
        model_id = "m" * 2048

        # Act
        recorder = DatabaseAgentRecorder(conversation, model_id=model_id)

        # Assert
        recorder.run.refresh_from_db()
        self.assertEqual(recorder.run.model_id, model_id)

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
        rows = list(conversation.transcript_entries.order_by("sequence"))
        self.assertEqual([r.sequence for r in rows], [0, 1, 2, 3])
        self.assertEqual(
            [{"role": r.role, "content": r.content} for r in rows],
            serialize_messages(result.messages),
        )
        # Provenance: backend seed, agent turn, tool results, agent answer.
        self.assertEqual(
            [r.source for r in rows], ["backend", "agent", "tool", "agent"]
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

    def test_build_context_ignores_unknown_additive_blocks(self):
        # Arrange: one row mixes a future block with known text, while another
        # contains only a future block that cannot be sent to this provider.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        AgentTranscriptEntry.objects.create(
            conversation=conversation,
            run=recorder.run,
            sequence=0,
            role="user",
            source=AgentTranscriptEntry.Source.BACKEND,
            content=[
                {"type": "future_block", "payload": {"value": 1}},
                {"type": "text", "text": "known content"},
            ],
        )
        AgentTranscriptEntry.objects.create(
            conversation=conversation,
            run=recorder.run,
            sequence=1,
            role="assistant",
            source=AgentTranscriptEntry.Source.AGENT,
            content=[{"type": "future_block", "payload": {"value": 2}}],
        )

        # Act
        context = build_context(conversation)

        # Assert: supported content survives and an empty provider message does not.
        self.assertEqual(
            context,
            [Message(role="user", content=[TextBlock(text="known content")])],
        )

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
        rows = list(conversation.transcript_entries.order_by("sequence"))
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

    def test_unexpected_setup_error_finalizes_the_run_as_failed(self):
        # Arrange
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        provider = ExplodingRenderProvider([])
        agent = _build_agent(provider, recorder=recorder)

        # Act
        with self.assertRaisesRegex(ValueError, "tool rendering exploded"):
            agent.run("hi")

        # Assert: the seed landed before setup failed and the run is terminal.
        run = recorder.run
        run.refresh_from_db()
        self.assertEqual(run.status, AgentRun.Status.FAILED)
        self.assertEqual(run.iterations, 0)
        self.assertEqual(run.error_message, "tool rendering exploded")
        self.assertEqual(conversation.transcript_entries.count(), 1)

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
        block = conversation.transcript_entries.get().content[0]
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
        block = conversation.transcript_entries.get().content[0]
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
        rows = list(conversation.transcript_entries.order_by("sequence"))
        self.assertEqual([r.sequence for r in rows], [0, 1, 2, 3])
        self.assertEqual([r.run_id for r in rows[:2]], [first.run.id] * 2)
        self.assertEqual([r.run_id for r in rows[2:]], [second.run.id] * 2)
        self.assertEqual(rows[2].content[0]["text"], "follow up")
        self.assertEqual(AgentRun.objects.filter(conversation=conversation).count(), 2)

    def test_recorders_allocate_sequences_when_runs_overlap(self):
        # Arrange: both runs start before either has written a message.
        conversation = _make_conversation()
        first = DatabaseAgentRecorder(conversation)
        second = DatabaseAgentRecorder(conversation)

        # Act
        first.record_message(
            Message(role="user", content=[TextBlock(text="first run")])
        )
        second.record_message(
            Message(role="user", content=[TextBlock(text="second run")])
        )

        # Assert: each run received a distinct position in the shared log.
        rows = list(conversation.transcript_entries.order_by("sequence"))
        self.assertEqual([row.sequence for row in rows], [0, 1])
        self.assertEqual([row.run_id for row in rows], [first.run.id, second.run.id])

    def test_hook_database_errors_do_not_break_an_outer_transaction(self):
        # Arrange
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        invalid_message = Message(
            role="r" * 100,
            content=[TextBlock(text="invalid role length")],
        )
        invalid_result = AgentResult(
            messages=[],
            final_text="",
            stop_reason="s" * 100,
            iterations=0,
        )

        # Act / Assert: both insert and terminal-update failures roll back to
        # their own savepoints; queries in the caller's transaction still work.
        with transaction.atomic():
            with self.assertRaises(DataError):
                recorder.record_message(invalid_message)
            self.assertTrue(
                AgentConversation.objects.filter(pk=conversation.pk).exists()
            )

            with self.assertRaises(DataError):
                recorder.on_run_finished(invalid_result)
            self.assertTrue(AgentRun.objects.filter(pk=recorder.run.pk).exists())

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

    def test_human_prompt_source_labels_the_prompt_turn(self):
        # Arrange: a chat-style run whose prompt is the user's verbatim text.
        conversation = _make_conversation(kind=AgentConversation.Kind.NOTEBOOK_CHAT)
        recorder = DatabaseAgentRecorder(
            conversation, prompt_source=AgentTranscriptEntry.Source.HUMAN
        )
        provider = FakeProvider([_build_text_turn("hello back")])
        agent = _build_agent(provider, recorder=recorder)

        # Act
        agent.run("hello")

        # Assert: the prompt row is human-authored; no wrapped text to carry.
        rows = list(conversation.transcript_entries.order_by("sequence"))
        self.assertEqual([r.source for r in rows], ["human", "agent"])
        self.assertIsNone(rows[0].meta)
        chat_messages = list(conversation.chat_messages.order_by("sequence"))
        self.assertEqual(
            [message.role for message in chat_messages],
            [AgentChatMessage.Role.USER, AgentChatMessage.Role.ASSISTANT],
        )
        self.assertEqual(recorder.run.trigger_message, chat_messages[0])
        self.assertEqual(chat_messages[1].produced_by_run, recorder.run)
        self.assertEqual(chat_messages[1].reply_to, chat_messages[0])

    def test_wrapped_prompt_stores_human_text_as_a_chat_message(self):
        # Arrange: a backend template embedding the user's words.
        conversation = _make_conversation(kind=AgentConversation.Kind.NOTEBOOK_CHAT)
        recorder = DatabaseAgentRecorder(
            conversation, human_text="find papers on froth flotation"
        )
        provider = FakeProvider([_build_tool_turn("t1"), _build_text_turn("done")])
        agent = _build_agent(provider, recorder=recorder)

        # Act
        agent.run(
            "Notebook context: ...\nThe user says: find papers on froth flotation"
        )

        # Assert: the product chat record carries the user's words while the
        # internal transcript retains the backend-templated provider prompt.
        rows = list(conversation.transcript_entries.order_by("sequence"))
        self.assertIsNone(rows[0].meta)
        self.assertIn("Notebook context", rows[0].content[0]["text"])
        self.assertEqual([r.meta for r in rows[1:]], [None, None, None])
        user_message = conversation.chat_messages.get(role="user")
        self.assertEqual(
            user_message.content,
            [{"type": "text", "text": "find papers on froth flotation"}],
        )
        self.assertEqual(user_message.transcript_entry, rows[0])

    def test_retry_reuses_the_trigger_without_duplicating_the_user_message(self):
        # Arrange: persist the product message before starting its first run.
        conversation = _make_conversation(kind=AgentConversation.Kind.NOTEBOOK_CHAT)
        trigger = AgentChatMessage.objects.create(
            conversation=conversation,
            sequence=0,
            role=AgentChatMessage.Role.USER,
            content=[{"type": "text", "text": "hello"}],
        )
        first = DatabaseAgentRecorder(
            conversation,
            trigger_message=trigger,
            prompt_source=AgentTranscriptEntry.Source.HUMAN,
        )
        _build_agent(
            FakeProvider([_build_text_turn("first answer")]), recorder=first
        ).run("hello")

        # Act: retry the same product message as a distinct execution.
        retry = DatabaseAgentRecorder(
            conversation,
            trigger_message=trigger,
            retry_of=first.run,
            prompt_source=AgentTranscriptEntry.Source.HUMAN,
        )
        _build_agent(
            FakeProvider([_build_text_turn("retry answer")]), recorder=retry
        ).run("hello")

        # Assert: both attempts have lineage to one user message.
        retry.run.refresh_from_db()
        trigger.refresh_from_db()
        self.assertEqual(retry.run.trigger_message, trigger)
        self.assertEqual(retry.run.retry_of, first.run)
        self.assertEqual(
            trigger.transcript_entry,
            first.run.transcript_entries.order_by("sequence").first(),
        )
        chat_messages = list(conversation.chat_messages.order_by("sequence"))
        self.assertEqual(
            [message.role for message in chat_messages],
            ["user", "assistant", "assistant"],
        )
        self.assertEqual(
            [message.reply_to_id for message in chat_messages[1:]],
            [trigger.id, trigger.id],
        )


class BuildChatViewTests(TestCase):
    def test_shows_human_words_and_agent_answers_only(self):
        # Arrange: a wrapped prompt, a tool round, then a text answer.
        conversation = _make_conversation(kind=AgentConversation.Kind.NOTEBOOK_CHAT)
        recorder = DatabaseAgentRecorder(conversation, human_text="what the user said")
        provider = FakeProvider(
            [_build_tool_turn("t1"), _build_text_turn("here is your answer")]
        )
        _build_agent(provider, recorder=recorder).run("templated prompt")

        # Act
        view = build_chat_view(conversation)

        # Assert: scaffolding and tool traffic are gone; the wrapped prompt
        # renders as the user's words, in sequence order.
        self.assertEqual(
            [(entry["sender"], entry["text"]) for entry in view],
            [("user", "what the user said"), ("agent", "here is your answer")],
        )
        self.assertEqual([entry["sequence"] for entry in view], [0, 1])
        for entry in view:
            self.assertIn("id", entry)
            self.assertIn("timestamp", entry)

    def test_renders_a_verbatim_human_turn_from_its_content(self):
        # Arrange: chat-style run -- the prompt is the human's own text.
        conversation = _make_conversation(kind=AgentConversation.Kind.NOTEBOOK_CHAT)
        recorder = DatabaseAgentRecorder(
            conversation, prompt_source=AgentTranscriptEntry.Source.HUMAN
        )
        provider = FakeProvider([_build_text_turn("hi")])
        _build_agent(provider, recorder=recorder).run("hello there")

        # Act
        view = build_chat_view(conversation)

        # Assert
        self.assertEqual(
            [(entry["sender"], entry["text"]) for entry in view],
            [("user", "hello there"), ("agent", "hi")],
        )

    def test_headless_run_does_not_create_product_chat_messages(self):
        # Arrange: a headless run -- the seed is pure scaffolding.
        conversation = _make_conversation()
        recorder = DatabaseAgentRecorder(conversation)
        provider = FakeProvider([_build_text_turn("drafted")])
        _build_agent(provider, recorder=recorder).run("system-composed prompt")

        # Act
        view = build_chat_view(conversation)

        # Assert: a headless workflow has an internal transcript but no chat.
        self.assertEqual(view, [])
