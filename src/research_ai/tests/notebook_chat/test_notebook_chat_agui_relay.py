import asyncio
import copy
import json
from unittest import IsolatedAsyncioTestCase

from channels.layers import InMemoryChannelLayer

from research_ai.services.notebook_chat.agui_relay import KEEPALIVE, ChatRelay
from research_ai.services.notebook_chat.events import (
    EVENT_TYPE,
    TURN_CANCELLED,
    TURN_FAILED,
    TURN_FINISHED,
    TURN_PROGRESS,
    conversation_group,
)
from research_ai.services.notebook_chat.service import ACTIVITY_ALL, ACTIVITY_LIVE
from research_ai.services.notebook_chat.streaming import STREAM_DELTA

CONVERSATION_ID = 7
EXECUTION_ID = 10


def _execution(status="RUNNING", **extra):
    return {
        "id": EXECUTION_ID,
        "trigger_message_id": 1,
        "status": status,
        "model": "model-a",
        "routed_model": None,
        "phase": {"state": "thinking", "label": "Thinking"},
        "error": None,
        "assistant_message_pending": False,
        "activity": [],
        **extra,
    }


def _chat(execution, *messages):
    user = {"id": 1, "role": "user", "content": "Hi", "execution_id": None}
    return {
        "conversation_id": CONVERSATION_ID,
        "messages": [user, *messages],
        "executions": [execution] if execution else [],
    }


def _answer(content="Done."):
    return {
        "id": 2,
        "role": "assistant",
        "content": content,
        "execution_id": EXECUTION_ID,
    }


class FakeChat:
    """Stands in for the service: returns the current chat per scope."""

    def __init__(self, chat):
        self.chat = chat
        self.scopes = []
        self.loaded = asyncio.Event()

    async def load(self, scope):
        self.scopes.append(scope)
        self.loaded.set()
        chat = copy.deepcopy(self.chat)
        if scope == ACTIVITY_LIVE:
            # The live scope omits activity for turns it considers settled.
            for execution in chat["executions"]:
                if execution["status"] not in ("PENDING", "RUNNING"):
                    execution.pop("activity", None)
        return chat


def _parse(frame):
    if frame == KEEPALIVE:
        return {"type": "KEEPALIVE"}
    assert frame.startswith("data: ") and frame.endswith("\n\n"), frame
    return json.loads(frame[len("data: ") : -2])


class ChatRelayTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.layer = InMemoryChannelLayer()

    def _relay(self, fake, **options):
        return ChatRelay(
            conversation_id=CONVERSATION_ID,
            thread_id=str(CONVERSATION_ID),
            run_id="run-1",
            load_chat=fake.load,
            channel_layer=self.layer,
            snapshot_debounce_seconds=0.0,
            **options,
        )

    async def _publish(self, kind, **data):
        await self.layer.group_send(
            conversation_group(CONVERSATION_ID),
            {
                "type": EVENT_TYPE,
                "data": {
                    "conversation_id": CONVERSATION_ID,
                    "execution_id": EXECUTION_ID,
                    "kind": kind,
                    **data,
                },
            },
        )

    async def _run(self, relay, fake, script=None, execution_id=EXECUTION_ID):
        """Collect the relay's events while ``script`` publishes to it."""
        events = []

        async def collect():
            # Appended as they arrive: scripts watch the list mid-stream.
            async for frame in relay.stream(execution_id):
                events.append(_parse(frame))  # noqa: PERF401

        async with asyncio.timeout(5):
            task = asyncio.create_task(collect())
            if script is not None:
                await fake.loaded.wait()
                await script(events)
            await task
        return events

    async def _until(self, events, event_type):
        while not any(event["type"] == event_type for event in events):
            await asyncio.sleep(0.005)

    async def test_an_idle_chat_sends_history_and_finishes(self):
        # Arrange
        fake = FakeChat(_chat(_execution(status="SUCCEEDED"), _answer()))

        # Act
        events = await self._run(self._relay(fake), fake, execution_id=None)

        # Assert
        self.assertEqual(
            [event["type"] for event in events],
            ["RUN_STARTED", "MESSAGES_SNAPSHOT", "RUN_FINISHED"],
        )
        self.assertEqual(events[0]["threadId"], "7")
        self.assertEqual(events[0]["runId"], "run-1")
        self.assertEqual(events[0]["protocolVersion"], "1.0")
        self.assertNotIn("metadata", events[0])
        self.assertEqual([m["id"] for m in events[1]["messages"]], ["msg-1", "msg-2"])
        self.assertEqual(fake.scopes, [ACTIVITY_ALL])
        self.assertEqual(
            events[1]["metadata"],
            {"@ag-ui/client": {"authoritativeActivityTypes": ["execution"]}},
        )

    async def test_a_running_turn_streams_until_it_finishes(self):
        # Arrange
        stream = {
            "id": "10:1",
            "sequence": 1,
            "iteration": 1,
            "items": [{"id": "n", "type": "narration", "text": "Wor"}],
        }
        fake = FakeChat(_chat(_execution(stream=stream)))

        async def script(events):
            await self._until(events, "TEXT_MESSAGE_CONTENT")
            await self._publish(
                STREAM_DELTA,
                stream_id="10:1",
                sequence=2,
                iteration=1,
                deltas=[{"id": "n", "type": "narration", "delta": "king"}],
            )
            while sum(e["type"] == "TEXT_MESSAGE_CONTENT" for e in events) < 2:
                await asyncio.sleep(0.005)
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer("Working."))
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        self.assertEqual(
            [event["type"] for event in events],
            [
                "RUN_STARTED",
                "MESSAGES_SNAPSHOT",
                "TEXT_MESSAGE_START",
                "TEXT_MESSAGE_CONTENT",
                "TEXT_MESSAGE_CONTENT",
                "TEXT_MESSAGE_END",
                "MESSAGES_SNAPSHOT",
                "RUN_FINISHED",
            ],
        )
        self.assertEqual(events[0]["metadata"], {"execution_id": EXECUTION_ID})
        self.assertEqual(events[4]["delta"], "king")
        self.assertEqual(events[6]["messages"][-1]["content"], "Working.")
        self.assertNotIn("outcome", events[-1])

    async def test_a_stopped_turn_finishes_with_a_cancelled_outcome(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))

        async def script(events):
            fake.chat = _chat(_execution(status="CANCELLED"))
            await self._publish(TURN_CANCELLED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        self.assertEqual(events[-1]["outcome"], {"type": "cancelled"})

    async def test_a_failed_turn_ends_in_a_run_error(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))
        error = {"code": "provider_busy", "message": "Overloaded.", "retryable": True}

        async def script(events):
            fake.chat = _chat(_execution(status="FAILED", error=error))
            await self._publish(TURN_FAILED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        self.assertEqual(events[-1]["type"], "RUN_ERROR")
        self.assertEqual(events[-1]["code"], "provider_busy")
        self.assertEqual(events[-1]["message"], "Overloaded.")

    async def test_a_sequence_gap_is_repaired_from_a_snapshot(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))

        async def script(events):
            fake.chat = _chat(
                _execution(
                    stream={
                        "id": "10:1",
                        "sequence": 3,
                        "iteration": 1,
                        "items": [{"id": "n", "type": "narration", "text": "abc"}],
                    }
                )
            )
            await self._publish(
                STREAM_DELTA,
                stream_id="10:1",
                sequence=3,
                iteration=1,
                deltas=[{"id": "n", "type": "narration", "delta": "c"}],
            )
            await self._until(events, "TEXT_MESSAGE_CONTENT")
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer())
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        types = [event["type"] for event in events]
        self.assertEqual(
            types[:5],
            [
                "RUN_STARTED",
                "MESSAGES_SNAPSHOT",
                "MESSAGES_SNAPSHOT",
                "TEXT_MESSAGE_START",
                "TEXT_MESSAGE_CONTENT",
            ],
        )
        self.assertEqual(events[4]["delta"], "abc")
        self.assertEqual(fake.scopes[:2], [ACTIVITY_ALL, ACTIVITY_LIVE])

    async def test_durable_progress_sends_a_snapshot(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))
        call = {"type": "tool_call", "tool": "read_note", "status": "in_progress"}

        async def script(events):
            fake.chat = _chat(_execution(activity=[call]))
            await self._publish(TURN_PROGRESS)
            while sum(e["type"] == "MESSAGES_SNAPSHOT" for e in events) < 2:
                await asyncio.sleep(0.005)
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer())
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        snapshots = [e for e in events if e["type"] == "MESSAGES_SNAPSHOT"]
        tool_calls = [m for m in snapshots[1]["messages"] if m.get("toolCalls")]
        self.assertEqual(tool_calls[0]["toolCalls"][0]["function"]["name"], "read_note")

    async def test_settled_activity_is_reused_from_the_first_load(self):
        # Arrange
        narration = {"type": "narration", "text": "Looked it up.", "at": None}
        fake = FakeChat(_chat(_execution(activity=[narration])))

        async def script(events):
            settled = _execution(status="SUCCEEDED", activity=[narration])
            fake.chat = _chat(settled, _answer())
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        final = [e for e in events if e["type"] == "MESSAGES_SNAPSHOT"][-1]
        self.assertIn("Looked it up.", [m.get("content") for m in final["messages"]])

    async def test_waits_for_an_answer_that_is_still_publishing(self):
        # Arrange
        fake = FakeChat(
            _chat(_execution(status="SUCCEEDED", assistant_message_pending=True))
        )
        relay = self._relay(fake, answer_poll_seconds=0.01)

        async def script(events):
            while len(fake.scopes) < 2:
                await asyncio.sleep(0.005)
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer("Late."))

        # Act
        events = await self._run(relay, fake, script)

        # Assert
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
        final = [e for e in events if e["type"] == "MESSAGES_SNAPSHOT"][-1]
        self.assertEqual(final["messages"][-1]["content"], "Late.")

    async def test_a_quiet_turn_sends_keepalives(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))
        relay = self._relay(fake, keepalive_seconds=0.01)

        async def script(events):
            await self._until(events, "KEEPALIVE")
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer())
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(relay, fake, script)

        # Assert
        self.assertIn("KEEPALIVE", [event["type"] for event in events])
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")

    async def test_events_for_other_turns_are_ignored(self):
        # Arrange
        fake = FakeChat(_chat(_execution()))

        async def script(events):
            await self.layer.group_send(
                conversation_group(CONVERSATION_ID),
                {
                    "type": EVENT_TYPE,
                    "data": {"execution_id": 99, "kind": TURN_FINISHED},
                },
            )
            await asyncio.sleep(0.05)
            self.assertEqual(fake.scopes, [ACTIVITY_ALL])
            fake.chat = _chat(_execution(status="SUCCEEDED"), _answer())
            await self._publish(TURN_FINISHED)

        # Act
        events = await self._run(self._relay(fake), fake, script)

        # Assert
        self.assertEqual(events[-1]["type"], "RUN_FINISHED")
