"""Server-sent AG-UI stream for one notebook chat.

The worker keeps publishing the same per-conversation channel-layer events the
WebSocket consumer forwards (see ``events``). :class:`ChatRelay` joins that
group as one more subscriber and re-expresses what it hears as an AG-UI run:

1. ``RUN_STARTED``, then a ``MESSAGES_SNAPSHOT`` of the whole chat.
2. While the watched turn runs: its transient ``stream_delta`` batches as
   streaming text, reasoning and tool-call events, and after every durable
   change (``turn_progress`` and friends) a fresh snapshot, debounced.
3. When the turn settles: one last snapshot and ``RUN_FINISHED`` (with a
   ``cancelled`` outcome for a stopped turn) or ``RUN_ERROR``.

The relay never drives the turn. A dropped connection only ends the relay; the
turn keeps running in its worker and a later connect picks it up again. That
is the same "transport is best-effort, durable state is the truth" contract
the WebSocket path has, so every gap is repaired by taking a snapshot.

Snapshots after the first read only the activity of turns the client may not
hold settled (``ACTIVITY_LIVE``) and reuse what this relay already loaded for
the rest, so a long chat costs one full read per connection.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from ag_ui.core import (
    PROTOCOL_VERSION,
    BaseEvent,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunStartedEvent,
)
from ag_ui.encoder import EventEncoder
from channels.layers import get_channel_layer

from research_ai.models import AgentExecution
from research_ai.services.notebook_chat.agui import (
    ACTIVE_STATUSES,
    StreamPreview,
    messages_snapshot,
)
from research_ai.services.notebook_chat.events import (
    EVENT_TYPE,
    TURN_CANCELLED,
    TURN_FAILED,
    TURN_FINISHED,
    conversation_group,
)
from research_ai.services.notebook_chat.service import ACTIVITY_ALL, ACTIVITY_LIVE
from research_ai.services.notebook_chat.streaming import STREAM_DELTA

logger = logging.getLogger(__name__)

# SSE comment the AG-UI HTTP binding allows; keeps proxies from timing out a
# quiet turn (a long tool call can go minutes without an event).
KEEPALIVE = ": keep-alive\n\n"
KEEPALIVE_SECONDS = 15.0
# Durable events arrive in bursts (one per trace write); coalesce them.
SNAPSHOT_DEBOUNCE_SECONDS = 0.25
# A succeeded turn whose answer has not published yet publishes without an
# event of its own, so the relay polls for it for a bounded time.
ANSWER_POLL_SECONDS = 1.0
ANSWER_WAIT_SECONDS = 30.0

_TERMINAL_KINDS = frozenset({TURN_FINISHED, TURN_FAILED, TURN_CANCELLED})

ChatLoader = Callable[[str], Awaitable[dict]]


class ChatRelay:
    """One SSE connection's view of a chat, as an AG-UI run.

    ``load_chat(scope)`` returns the chat representation for an activity
    scope; it is injected so the relay stays free of request and ORM
    concerns. ``thread_id`` and ``run_id`` are echoed from the client's
    ``RunAgentInput``.
    """

    def __init__(
        self,
        *,
        conversation_id: int,
        thread_id: str,
        run_id: str,
        load_chat: ChatLoader,
        channel_layer=None,
        clock=time.monotonic,
        keepalive_seconds: float = KEEPALIVE_SECONDS,
        snapshot_debounce_seconds: float = SNAPSHOT_DEBOUNCE_SECONDS,
        answer_poll_seconds: float = ANSWER_POLL_SECONDS,
        answer_wait_seconds: float = ANSWER_WAIT_SECONDS,
    ):
        self.conversation_id = conversation_id
        self.thread_id = thread_id
        self.run_id = run_id
        self._load_chat = load_chat
        self._channel_layer = channel_layer
        self._clock = clock
        self._keepalive_seconds = keepalive_seconds
        self._debounce_seconds = snapshot_debounce_seconds
        self._answer_poll_seconds = answer_poll_seconds
        self._answer_wait_seconds = answer_wait_seconds
        self._activity: dict[int, list] = {}

    async def stream(self, execution_id: int | None = None) -> AsyncIterator[str]:
        """Encoded SSE frames for the run watching ``execution_id``.

        With no ``execution_id`` the relay watches the chat's active turn if
        it has one, and otherwise ends after the snapshot -- the "connect"
        case, which loads history and rejoins a turn already in flight.
        """
        encoder = EventEncoder()
        yield encoder.encode(
            RunStartedEvent(
                thread_id=self.thread_id,
                run_id=self.run_id,
                protocol_version=PROTOCOL_VERSION,
                # The turn this run started, so a client can match it to the
                # chat's REST representation.
                metadata=(
                    {"execution_id": execution_id} if execution_id is not None else None
                ),
            )
        )
        layer = self._channel_layer or get_channel_layer()
        group = conversation_group(self.conversation_id)
        # Subscribe before the first read, so nothing published between the
        # read and the subscription is lost.
        channel = await layer.new_channel()
        await layer.group_add(group, channel)
        try:
            async for frame in self._frames(layer, channel, execution_id, encoder):
                yield frame
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "notebook chat AG-UI relay failed (conversation=%s)",
                self.conversation_id,
            )
            yield encoder.encode(
                RunErrorEvent(
                    message="The chat stream failed. Reload to see the latest.",
                    code="stream_failed",
                )
            )
        finally:
            try:
                await layer.group_discard(group, channel)
            except Exception:  # noqa: BLE001 - cleanup must not mask the exit
                logger.warning("could not leave %s", group, exc_info=True)

    async def _frames(
        self, layer, channel: str, execution_id: int | None, encoder: EventEncoder
    ) -> AsyncIterator[str]:
        chat = await self._load(ACTIVITY_ALL)
        yield encoder.encode(messages_snapshot(chat))
        target = execution_id if execution_id is not None else _active_id(chat)
        execution = _find(chat, target)
        # Nothing running (or a turn that settled before we subscribed): the
        # snapshot above is already final, apart from an answer that is still
        # publishing.
        if execution is None or (
            execution["status"] not in ACTIVE_STATUSES
            and not execution["assistant_message_pending"]
        ):
            yield encoder.encode(self._finish(execution))
            return

        preview = StreamPreview(target)
        # A turn that settled with its answer still publishing starts out
        # dirty, so the loop goes straight to polling for the answer.
        dirty_since: float | None = self._clock()
        force = True
        if execution["status"] in ACTIVE_STATUSES:
            for event in preview.replay(execution.get("stream")):
                yield encoder.encode(event)
            dirty_since = None
            force = False
        answer_deadline: float | None = None
        last_frame_at = self._clock()

        while True:
            chat = None
            now = self._clock()
            if dirty_since is not None:
                wait = 0.0 if force else self._debounce_seconds - (now - dirty_since)
            elif answer_deadline is not None:
                wait = self._answer_poll_seconds
            else:
                wait = self._keepalive_seconds - (now - last_frame_at)
            message = await _receive(layer, channel, max(0.0, wait))

            if message is not None:
                data = message.get("data") or {}
                if (
                    message.get("type") != EVENT_TYPE
                    or data.get("execution_id") != target
                ):
                    continue
                kind = data.get("kind")
                if kind == STREAM_DELTA:
                    events = preview.apply(data)
                    if events is not None:
                        for event in events:
                            yield encoder.encode(event)
                        if events:
                            last_frame_at = self._clock()
                        continue
                    force = True
                elif kind in _TERMINAL_KINDS:
                    force = True
                if dirty_since is None:
                    dirty_since = self._clock()
                if not force and self._clock() - dirty_since < self._debounce_seconds:
                    continue
            elif dirty_since is None and answer_deadline is None:
                # Quiet. Channel-layer delivery is best-effort, so check the
                # durable state in case the turn's terminal event was lost.
                chat = await self._load(ACTIVITY_LIVE)
                execution = _find(chat, target)
                if execution is not None and execution["status"] in ACTIVE_STATUSES:
                    yield KEEPALIVE
                    last_frame_at = self._clock()
                    continue
            elif dirty_since is None:
                # Polling for an answer that is still publishing.
                force = True

            # Refresh from durable state.
            if chat is None:
                chat = await self._load(ACTIVITY_LIVE)
            dirty_since = None
            force = False
            for event in preview.close():
                yield encoder.encode(event)
            yield encoder.encode(messages_snapshot(chat))
            last_frame_at = self._clock()
            execution = _find(chat, target)
            if execution is not None and execution["status"] in ACTIVE_STATUSES:
                for event in preview.replay(execution.get("stream")):
                    yield encoder.encode(event)
                continue
            if execution is not None and execution["assistant_message_pending"]:
                if answer_deadline is None:
                    answer_deadline = self._clock() + self._answer_wait_seconds
                if self._clock() < answer_deadline:
                    continue
            yield encoder.encode(self._finish(execution))
            return

    async def _load(self, scope: str) -> dict:
        """The chat, with activity this relay already holds filled back in."""
        chat = await self._load_chat(scope)
        for execution in chat["executions"]:
            if "activity" in execution:
                self._activity[execution["id"]] = execution["activity"]
            else:
                execution["activity"] = self._activity.get(execution["id"], [])
        return chat

    def _finish(self, execution: dict | None) -> BaseEvent:
        if execution is None:
            return RunFinishedEvent(thread_id=self.thread_id, run_id=self.run_id)
        status = execution["status"]
        if status == AgentExecution.Status.CANCELLED:
            return RunFinishedEvent(
                thread_id=self.thread_id,
                run_id=self.run_id,
                outcome=RunFinishedCancelledOutcome(),
            )
        if status in (AgentExecution.Status.FAILED, AgentExecution.Status.INTERRUPTED):
            error = execution.get("error") or {}
            return RunErrorEvent(
                message=error.get("message") or "The agent could not finish.",
                code=error.get("code") or status.lower(),
            )
        return RunFinishedEvent(thread_id=self.thread_id, run_id=self.run_id)


async def _receive(layer, channel: str, timeout: float) -> dict | None:
    try:
        async with asyncio.timeout(timeout):
            return await layer.receive(channel)
    except TimeoutError:
        return None


def _active_id(chat: dict) -> int | None:
    """The turn a connect should follow: one running, or one whose answer is
    still publishing."""
    active = [
        e
        for e in chat["executions"]
        if e["status"] in ACTIVE_STATUSES or e["assistant_message_pending"]
    ]
    return active[-1]["id"] if active else None


def _find(chat: dict, execution_id: int | None) -> dict | None:
    if execution_id is None:
        return None
    return next((e for e in chat["executions"] if e["id"] == execution_id), None)
