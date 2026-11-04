"""AG-UI projection of notebook chats.

AG-UI (https://docs.ag-ui.com) is the event protocol CopilotKit speaks to an
agent. This module translates what notebook chat already exposes into it,
without touching how turns run:

- :func:`history_messages` turns the user-safe chat representation (messages
  plus each turn's public activity feed) into AG-UI messages, for
  ``MESSAGES_SNAPSHOT``. Tool calls carry only the public activity fields --
  label, detail, sources, the note version an edit produced -- never raw tool
  arguments or results, the same privacy line the REST projection draws.
- :class:`StreamPreview` turns the transient ``stream_delta`` batches the
  worker publishes into streaming AG-UI events: narration becomes a text
  message, readable thinking a reasoning message, and a tool call the model is
  composing a tool call whose arguments are ``{"label", "text"}``, where
  ``text`` is the prose an ``edit_note`` call is writing.

Previews are disposable. Durable state always arrives later as a snapshot,
which replaces them, so the preview only has to be right while it is shown.
"""

import json
from collections import defaultdict

from ag_ui.core import (
    ActivityMessage,
    AssistantMessage,
    BaseEvent,
    FunctionCall,
    Message,
    MessagesSnapshotEvent,
    ReasoningEndEvent,
    ReasoningMessage,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCall,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolMessage,
    UserMessage,
)
from django.core.serializers.json import DjangoJSONEncoder

from research_ai.models import AgentExecution
from research_ai.services.notebook_chat.streaming import (
    ITEM_NARRATION,
    ITEM_THINKING,
    ITEM_TOOL_DRAFT,
)

# The activity message type CopilotKit renders for a turn's status line.
ACTIVITY_EXECUTION = "execution"

ACTIVE_STATUSES = frozenset(
    {AgentExecution.Status.PENDING, AgentExecution.Status.RUNNING}
)

# Fields of a public tool-call item that describe the call itself. They become
# the AG-UI tool call's arguments; the whole item becomes its result.
_TOOL_ARG_FIELDS = ("label", "detail")


def messages_snapshot(chat: dict) -> MessagesSnapshotEvent:
    """``MESSAGES_SNAPSHOT`` of the chat, authoritative for its status lines.

    The AG-UI client keeps activity messages a snapshot omits unless the
    snapshot claims their type; without the claim, a turn's "running" status
    line would outlive the turn.
    """
    return MessagesSnapshotEvent(
        messages=history_messages(chat),
        metadata={
            "@ag-ui/client": {"authoritativeActivityTypes": [ACTIVITY_EXECUTION]}
        },
    )


def chat_message_id(message_id: int) -> str:
    """The AG-UI id of a persisted chat message."""
    return f"msg-{message_id}"


def is_persisted_message_id(message_id: str) -> bool:
    """Whether ``message_id`` names a message the chat already holds."""
    prefix, _, number = message_id.partition("-")
    return prefix == "msg" and number.isdigit()


def history_messages(chat: dict) -> list[Message]:
    """The chat as AG-UI messages, in transcript order.

    ``chat`` is :meth:`NotebookChatService.representation` with every
    execution's ``activity`` present. Each user message is followed by the
    turns it triggered (retries included, oldest first): the turn's activity,
    a status line while it runs or when it did not succeed, and its published
    answer. Turns whose trigger is gone, and answers no listed turn produced,
    keep their own position.
    """
    # Executions not yet placed, in attempt order.
    pending = {execution["id"]: execution for execution in chat["executions"]}
    by_trigger = defaultdict(list)
    for execution in chat["executions"]:
        by_trigger[execution["trigger_message_id"]].append(execution["id"])
    answers = {
        message["execution_id"]: message
        for message in chat["messages"]
        if message["role"] == "assistant" and message["execution_id"] is not None
    }
    placed_answers: set[int] = set()
    messages: list[Message] = []

    def place(execution_id: int) -> None:
        execution = pending.pop(execution_id, None)
        if execution is None:
            return
        answer = answers.get(execution_id)
        if answer is not None and answer["id"] in placed_answers:
            answer = None
        messages.extend(_execution_messages(execution, answer))
        if answer is not None:
            placed_answers.add(answer["id"])

    for message in chat["messages"]:
        role = message["role"]
        if role == "user":
            messages.append(_user_message(message))
            for execution_id in by_trigger.get(message["id"], []):
                place(execution_id)
        elif role == "assistant" and message["id"] not in placed_answers:
            if message["execution_id"] in pending:
                # A turn whose trigger is not shown: its activity and answer
                # go where the answer sits.
                place(message["execution_id"])
                continue
            messages.append(
                AssistantMessage(
                    id=chat_message_id(message["id"]), content=message["content"]
                )
            )
            placed_answers.add(message["id"])
    for execution_id in list(pending):
        place(execution_id)
    return messages


def _user_message(message: dict) -> UserMessage:
    return UserMessage(
        id=chat_message_id(message["id"]),
        content=message["content"],
        metadata={"attachments": _jsonable(message.get("attachments") or [])},
    )


def _execution_messages(execution: dict, answer: dict | None) -> list[Message]:
    messages: list[Message] = []
    for index, item in enumerate(execution.get("activity") or []):
        messages.extend(_activity_messages(f"exec-{execution['id']}-{index}", item))
    status = _status_message(execution)
    if status is not None:
        messages.append(status)
    if answer is not None:
        messages.append(
            AssistantMessage(
                id=chat_message_id(answer["id"]), content=answer["content"]
            )
        )
    return messages


def _activity_messages(message_id: str, item: dict) -> list[Message]:
    kind = item.get("type")
    if kind == "narration":
        return [AssistantMessage(id=message_id, content=item["text"])]
    if kind == "thinking":
        return [ReasoningMessage(id=message_id, role="reasoning", content=item["text"])]
    if kind != "tool_call":
        return []
    call_id = f"{message_id}-call"
    arguments = {field: item[field] for field in _TOOL_ARG_FIELDS if field in item}
    messages: list[Message] = [
        AssistantMessage(
            id=message_id,
            tool_calls=[
                ToolCall(
                    id=call_id,
                    type="function",
                    function=FunctionCall(
                        name=item.get("tool") or "tool",
                        arguments=json.dumps(arguments),
                    ),
                )
            ],
        )
    ]
    if item.get("status") != "in_progress":
        result = {key: value for key, value in item.items() if key != "type"}
        messages.append(
            ToolMessage(
                id=f"{message_id}-result",
                role="tool",
                tool_call_id=call_id,
                content=json.dumps(result, cls=DjangoJSONEncoder),
                error=item["status"] if item.get("status") == "failed" else None,
            )
        )
    return messages


def _status_message(execution: dict) -> ActivityMessage | None:
    """The turn's status line, or ``None`` for a plain success.

    A running turn reports its phase; a turn that failed, was stopped, or was
    interrupted reports its public error; a success says which model answered
    when the requested one declined.
    """
    status = execution["status"]
    active = status in ACTIVE_STATUSES
    succeeded = status == AgentExecution.Status.SUCCEEDED
    if succeeded and not execution.get("routed_model"):
        return None
    content = {
        "execution_id": execution["id"],
        "status": status.lower(),
        "model": execution.get("model"),
        "routed_model": execution.get("routed_model"),
    }
    if active:
        content["phase"] = execution.get("phase")
    elif not succeeded:
        content["error"] = execution.get("error")
    # The id changes whenever the line should move or change: the client keeps
    # a message it already holds where it was, so a stable id would leave a
    # status line written before the turn's activity stranded above it.
    activity_count = len(execution.get("activity") or [])
    return ActivityMessage(
        id=f"exec-{execution['id']}-status-{status.lower()}-{activity_count}",
        role="activity",
        activity_type=ACTIVITY_EXECUTION,
        content=_jsonable(content),
    )


def _jsonable(value):
    """``value`` with datetimes and other Django values as JSON primitives."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _escaped(text: str) -> str:
    """``text`` as the inside of a JSON string literal."""
    return json.dumps(text)[1:-1]


class StreamPreview:
    """Translates one execution's ``stream_delta`` batches into AG-UI events.

    Batches are applied in sequence order within one stream (one provider
    iteration, or one retry of it). :meth:`apply` returns ``None`` when the
    batch cannot be applied in order -- a gap, or a new stream while the old
    one is still on screen -- and the caller should repair: :meth:`close`,
    send a fresh durable snapshot, then :meth:`replay` the cached stream
    snapshot, which already contains every published batch.

    Invariant: :meth:`close` is only called right before a messages snapshot
    or the end of the run, so a closed preview is one the client no longer
    shows. A later delta for it re-opens it with its full text so far.
    """

    def __init__(self, execution_id: int):
        self.execution_id = execution_id
        self.stream_id: str | None = None
        self.iteration: int | None = None
        self.sequence = 0
        self.items: dict[str, dict] = {}
        self.has_draft_state = False

    def replay(self, stream: dict | None) -> list[BaseEvent]:
        """Adopt a cached stream snapshot and show its items from scratch."""
        self.stream_id = None
        self.iteration = None
        self.sequence = 0
        self.items = {}
        if not stream:
            return []
        self.stream_id = stream.get("id")
        self.iteration = stream.get("iteration")
        self.sequence = stream.get("sequence") or 0
        events: list[BaseEvent] = []
        for snapshot in stream.get("items") or []:
            item = self._item(snapshot)
            item["text"] = snapshot.get("text") or ""
            events.extend(self._open(item))
            if snapshot.get("blocks") is not None:
                events.append(self._draft_state(item, snapshot["blocks"]))
        return events

    def matches(self, stream: dict | None) -> bool:
        """Whether this preview already shows the cached ``stream``."""
        if not stream:
            return self.stream_id is None
        return (
            stream.get("id") == self.stream_id
            and (stream.get("sequence") or 0) == self.sequence
        )

    def apply(self, data: dict) -> list[BaseEvent] | None:
        """Events for one batch, ``[]`` for a stale one, ``None`` to repair."""
        stream_id = data.get("stream_id")
        sequence = data.get("sequence") or 0
        iteration = data.get("iteration")
        if stream_id != self.stream_id:
            if (
                self.iteration is not None
                and iteration is not None
                and iteration < self.iteration
            ):
                return []
            # Previews still on screen belong to a discarded attempt or an
            # earlier iteration; only a snapshot can take them down.
            if sequence != 1 or any(item["open"] for item in self.items.values()):
                return None
            self.stream_id = stream_id
            self.iteration = iteration
            self.sequence = 0
            self.items = {}
        if sequence <= self.sequence:
            return []
        if sequence != self.sequence + 1:
            return None
        self.sequence = sequence
        events: list[BaseEvent] = []
        for delta in data.get("deltas") or []:
            events.extend(self._apply_delta(delta))
        return events

    def close(self) -> list[BaseEvent]:
        """End every open preview; the caller is about to replace them."""
        events: list[BaseEvent] = []
        for item in self.items.values():
            if not item["open"]:
                continue
            item["open"] = False
            message_id = item["message_id"]
            if item["type"] == ITEM_NARRATION:
                events.append(TextMessageEndEvent(message_id=message_id))
            elif item["type"] == ITEM_THINKING:
                events.append(ReasoningMessageEndEvent(message_id=message_id))
                events.append(ReasoningEndEvent(message_id=message_id))
            else:
                events.append(ToolCallArgsEvent(tool_call_id=message_id, delta='"}'))
                events.append(ToolCallEndEvent(tool_call_id=message_id))
        if self.has_draft_state:
            events.append(StateSnapshotEvent(snapshot={}))
            self.has_draft_state = False
        return events

    def _apply_delta(self, delta: dict) -> list[BaseEvent]:
        item = self.items.get(delta.get("id"))
        if item is None:
            item = self._item(delta)
        fragment = delta.get("delta") or ""
        item["text"] += fragment
        events: list[BaseEvent] = []
        if not item["open"]:
            events.extend(self._open(item))
        elif fragment:
            events.append(self._content(item, fragment))
        if delta.get("blocks") is not None:
            events.append(self._draft_state(item, delta["blocks"]))
        return events

    def _item(self, source: dict) -> dict:
        item_id = source.get("id") or ""
        item = {
            "type": source.get("type"),
            "tool": source.get("tool") or "",
            "label": source.get("label") or "",
            "text": "",
            "open": False,
            "message_id": f"preview-{self.execution_id}-{item_id}",
        }
        self.items[item_id] = item
        return item

    def _open(self, item: dict) -> list[BaseEvent]:
        item["open"] = True
        message_id = item["message_id"]
        text = item["text"]
        if item["type"] == ITEM_NARRATION:
            events = [TextMessageStartEvent(message_id=message_id, role="assistant")]
        elif item["type"] == ITEM_THINKING:
            events = [
                ReasoningStartEvent(message_id=message_id),
                ReasoningMessageStartEvent(message_id=message_id, role="reasoning"),
            ]
        elif item["type"] == ITEM_TOOL_DRAFT:
            prefix = '{"label": ' + json.dumps(item["label"]) + ', "text": "'
            return [
                ToolCallStartEvent(
                    tool_call_id=message_id,
                    tool_call_name=item["tool"] or "tool",
                ),
                ToolCallArgsEvent(
                    tool_call_id=message_id, delta=prefix + _escaped(text)
                ),
            ]
        else:
            item["open"] = False
            return []
        if text:
            events.append(self._content(item, text))
        return events

    def _content(self, item: dict, fragment: str) -> BaseEvent:
        message_id = item["message_id"]
        if item["type"] == ITEM_NARRATION:
            return TextMessageContentEvent(message_id=message_id, delta=fragment)
        if item["type"] == ITEM_THINKING:
            return ReasoningMessageContentEvent(message_id=message_id, delta=fragment)
        return ToolCallArgsEvent(tool_call_id=message_id, delta=_escaped(fragment))

    def _draft_state(self, item: dict, blocks) -> BaseEvent:
        self.has_draft_state = True
        return StateSnapshotEvent(
            snapshot={
                "draft": {
                    "tool_call_id": item["message_id"],
                    "tool": item["tool"],
                    "blocks": blocks,
                }
            }
        )
