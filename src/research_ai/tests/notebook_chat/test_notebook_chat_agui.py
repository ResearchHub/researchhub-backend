import json
from unittest import TestCase

from ag_ui.core import (
    ActivityMessage,
    AssistantMessage,
    ReasoningMessage,
    ToolMessage,
    UserMessage,
)

from research_ai.services.notebook_chat.agui import (
    StreamPreview,
    history_messages,
    is_persisted_message_id,
)


def _execution(execution_id, trigger_id, status="SUCCEEDED", **extra):
    return {
        "id": execution_id,
        "trigger_message_id": trigger_id,
        "status": status,
        "model": "model-a",
        "routed_model": None,
        "phase": None,
        "error": None,
        "activity": [],
        **extra,
    }


def _chat(messages, executions):
    return {"conversation_id": 1, "messages": messages, "executions": executions}


def _user(message_id, content="Hi", **extra):
    return {
        "id": message_id,
        "role": "user",
        "content": content,
        "execution_id": None,
        **extra,
    }


def _answer(message_id, execution_id, content="Done."):
    return {
        "id": message_id,
        "role": "assistant",
        "content": content,
        "execution_id": execution_id,
    }


def _types(events):
    return [event.type.value for event in events]


class HistoryMessagesTests(TestCase):
    def test_orders_each_turn_after_the_message_that_triggered_it(self):
        # Arrange
        chat = _chat(
            [_user(1), _answer(2, 10), _user(3, "Again"), _answer(4, 11)],
            [_execution(10, 1), _execution(11, 3)],
        )

        # Act
        messages = history_messages(chat)

        # Assert
        self.assertEqual(
            [message.id for message in messages], ["msg-1", "msg-2", "msg-3", "msg-4"]
        )
        self.assertIsInstance(messages[0], UserMessage)
        self.assertIsInstance(messages[1], AssistantMessage)
        self.assertEqual(messages[1].content, "Done.")

    def test_activity_becomes_narration_reasoning_and_tool_calls(self):
        # Arrange
        activity = [
            {"type": "thinking", "text": "Let me look.", "at": None},
            {"type": "narration", "text": "Searching now.", "at": None},
            {
                "type": "tool_call",
                "tool": "web_search",
                "label": "Searched the web",
                "status": "succeeded",
                "detail": "crispr",
                "sources": [{"title": "A", "url": "https://a.test"}],
            },
        ]
        chat = _chat([_user(1)], [_execution(10, 1, activity=activity)])

        # Act
        messages = history_messages(chat)

        # Assert
        reasoning, narration, call, result = messages[1:]
        self.assertIsInstance(reasoning, ReasoningMessage)
        self.assertEqual(reasoning.content, "Let me look.")
        self.assertEqual(narration.content, "Searching now.")
        tool_call = call.tool_calls[0]
        self.assertEqual(tool_call.function.name, "web_search")
        self.assertEqual(
            json.loads(tool_call.function.arguments),
            {"label": "Searched the web", "detail": "crispr"},
        )
        self.assertIsInstance(result, ToolMessage)
        self.assertEqual(result.tool_call_id, tool_call.id)
        self.assertEqual(
            json.loads(result.content)["sources"][0]["url"], "https://a.test"
        )
        self.assertIsNone(result.error)

    def test_an_open_tool_call_has_no_result(self):
        # Arrange
        activity = [{"type": "tool_call", "tool": "read_note", "status": "in_progress"}]
        chat = _chat(
            [_user(1)],
            [_execution(10, 1, status="RUNNING", activity=activity, phase={})],
        )

        # Act
        messages = history_messages(chat)

        # Assert
        self.assertFalse(any(isinstance(m, ToolMessage) for m in messages))

    def test_a_failed_tool_call_reports_an_error(self):
        # Arrange
        activity = [{"type": "tool_call", "tool": "edit_note", "status": "failed"}]
        chat = _chat([_user(1)], [_execution(10, 1, activity=activity)])

        # Act
        result = history_messages(chat)[-1]

        # Assert
        self.assertEqual(result.error, "failed")

    def test_a_running_turn_reports_its_phase(self):
        # Arrange
        phase = {"state": "thinking", "label": "Thinking"}
        chat = _chat([_user(1)], [_execution(10, 1, status="RUNNING", phase=phase)])

        # Act
        status = history_messages(chat)[-1]

        # Assert
        self.assertIsInstance(status, ActivityMessage)
        self.assertEqual(status.activity_type, "execution")
        self.assertEqual(status.content["status"], "running")
        self.assertEqual(status.content["phase"], phase)

    def test_the_status_line_id_changes_as_the_turn_moves(self):
        # Arrange: the client keeps a known id in place, so the line must get
        # a new id to move below newly added activity.
        call = {"type": "tool_call", "tool": "read_note", "status": "in_progress"}
        before = _chat([_user(1)], [_execution(10, 1, status="RUNNING", phase={})])
        after = _chat(
            [_user(1)],
            [_execution(10, 1, status="RUNNING", phase={}, activity=[call])],
        )
        stopped = _chat([_user(1)], [_execution(10, 1, status="CANCELLED")])

        # Act
        ids = [history_messages(chat)[-1].id for chat in (before, after, stopped)]

        # Assert
        self.assertEqual(len(set(ids)), 3)

    def test_a_failed_turn_reports_its_public_error(self):
        # Arrange
        error = {"code": "agent_failed", "message": "Nope.", "retryable": True}
        chat = _chat([_user(1)], [_execution(10, 1, status="FAILED", error=error)])

        # Act
        status = history_messages(chat)[-1]

        # Assert
        self.assertEqual(status.content["status"], "failed")
        self.assertEqual(status.content["error"], error)

    def test_a_plain_success_has_no_status_line(self):
        # Arrange
        chat = _chat([_user(1), _answer(2, 10)], [_execution(10, 1)])

        # Act
        messages = history_messages(chat)

        # Assert
        self.assertFalse(any(isinstance(m, ActivityMessage) for m in messages))

    def test_turns_without_a_visible_trigger_are_kept(self):
        # Arrange
        chat = _chat([_answer(2, 10)], [_execution(10, 99)])

        # Act
        messages = history_messages(chat)

        # Assert
        self.assertEqual([m.id for m in messages], ["msg-2"])

    def test_user_attachments_ride_in_metadata(self):
        # Arrange
        attachment = {"id": 5, "filename": "paper.pdf"}
        chat = _chat([_user(1, attachments=[attachment])], [])

        # Act
        (message,) = history_messages(chat)

        # Assert
        self.assertEqual(message.metadata, {"attachments": [attachment]})

    def test_persisted_message_ids(self):
        self.assertTrue(is_persisted_message_id("msg-12"))
        self.assertFalse(is_persisted_message_id("msg-abc"))
        self.assertFalse(is_persisted_message_id("6c2b1c1e-client"))


def _delta(item_id, item_type, text="", **extra):
    return {"id": item_id, "type": item_type, "delta": text, **extra}


def _batch(sequence, *deltas, stream_id="10:1", iteration=1):
    return {
        "stream_id": stream_id,
        "sequence": sequence,
        "iteration": iteration,
        "deltas": list(deltas),
    }


class StreamPreviewTests(TestCase):
    def test_narration_streams_as_a_text_message(self):
        # Arrange
        preview = StreamPreview(10)

        # Act
        first = preview.apply(_batch(1, _delta("n", "narration", "Hel")))
        second = preview.apply(_batch(2, _delta("n", "narration", "lo")))
        closing = preview.close()

        # Assert
        self.assertEqual(_types(first), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"])
        self.assertEqual(first[0].message_id, "preview-10-n")
        self.assertEqual(second[0].delta, "lo")
        self.assertEqual(_types(closing), ["TEXT_MESSAGE_END"])

    def test_thinking_streams_as_a_reasoning_message(self):
        # Arrange
        preview = StreamPreview(10)

        # Act
        events = preview.apply(_batch(1, _delta("t", "thinking", "Hmm")))
        closing = preview.close()

        # Assert
        self.assertEqual(
            _types(events),
            [
                "REASONING_START",
                "REASONING_MESSAGE_START",
                "REASONING_MESSAGE_CONTENT",
            ],
        )
        self.assertEqual(_types(closing), ["REASONING_MESSAGE_END", "REASONING_END"])

    def test_a_tool_draft_streams_label_and_text_as_json_arguments(self):
        # Arrange
        preview = StreamPreview(10)
        start = _delta(
            "d", "tool_draft", "", tool="edit_note", label="Writing the note"
        )

        # Act
        events = preview.apply(_batch(1, start))
        events += preview.apply(
            _batch(2, _delta("d", "tool_draft", 'A "quoted"\nline'))
        )
        events += preview.close()

        # Assert
        self.assertEqual(events[0].tool_call_name, "edit_note")
        arguments = "".join(
            event.delta for event in events if event.type.value == "TOOL_CALL_ARGS"
        )
        self.assertEqual(
            json.loads(arguments),
            {"label": "Writing the note", "text": 'A "quoted"\nline'},
        )
        self.assertEqual(events[-1].type.value, "TOOL_CALL_END")

    def test_draft_blocks_are_published_as_state_and_cleared_on_close(self):
        # Arrange
        preview = StreamPreview(10)
        blocks = [{"type": "paragraph"}]

        # Act
        events = preview.apply(
            _batch(1, _delta("d", "tool_draft", "x", tool="edit_note", blocks=blocks))
        )
        closing = preview.close()

        # Assert
        self.assertEqual(events[-1].snapshot["draft"]["blocks"], blocks)
        self.assertEqual(closing[-1].snapshot, {})

    def test_duplicates_are_dropped_and_gaps_ask_for_repair(self):
        # Arrange
        preview = StreamPreview(10)
        preview.apply(_batch(1, _delta("n", "narration", "a")))

        # Act
        duplicate = preview.apply(_batch(1, _delta("n", "narration", "a")))
        gap = preview.apply(_batch(3, _delta("n", "narration", "c")))

        # Assert
        self.assertEqual(duplicate, [])
        self.assertIsNone(gap)

    def test_a_new_stream_over_an_open_preview_asks_for_repair(self):
        # Arrange
        preview = StreamPreview(10)
        preview.apply(_batch(1, _delta("n", "narration", "a")))

        # Act
        result = preview.apply(
            _batch(1, _delta("m", "narration", "b"), stream_id="10:2", iteration=2)
        )

        # Assert
        self.assertIsNone(result)

    def test_a_new_stream_after_a_snapshot_is_adopted(self):
        # Arrange
        preview = StreamPreview(10)
        preview.apply(_batch(1, _delta("n", "narration", "a")))
        preview.close()

        # Act
        result = preview.apply(
            _batch(1, _delta("m", "narration", "b"), stream_id="10:2", iteration=2)
        )

        # Assert
        self.assertEqual(_types(result), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"])

    def test_an_older_iteration_is_ignored(self):
        # Arrange
        preview = StreamPreview(10)
        preview.apply(
            _batch(1, _delta("n", "narration", "a"), stream_id="10:2", iteration=2)
        )

        # Act
        result = preview.apply(_batch(5, _delta("m", "narration", "b")))

        # Assert
        self.assertEqual(result, [])

    def test_replay_reopens_the_cached_snapshot_and_continues_from_it(self):
        # Arrange
        preview = StreamPreview(10)
        stream = {
            "id": "10:1",
            "sequence": 4,
            "iteration": 1,
            "items": [{"id": "n", "type": "narration", "text": "So far"}],
        }

        # Act
        replayed = preview.replay(stream)
        following = preview.apply(_batch(5, _delta("n", "narration", "!")))

        # Assert
        self.assertEqual(
            _types(replayed), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"]
        )
        self.assertEqual(replayed[1].delta, "So far")
        self.assertEqual(_types(following), ["TEXT_MESSAGE_CONTENT"])

    def test_a_delta_for_a_closed_preview_reopens_it_with_its_full_text(self):
        # Arrange
        preview = StreamPreview(10)
        preview.apply(_batch(1, _delta("n", "narration", "Hel")))
        preview.close()

        # Act
        events = preview.apply(_batch(2, _delta("n", "narration", "lo")))

        # Assert
        self.assertEqual(_types(events), ["TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT"])
        self.assertEqual(events[1].delta, "Hello")
