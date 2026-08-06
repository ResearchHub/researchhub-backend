"""Activity events extracted from persisted execution traces.

Trace rows (:class:`AgentExecutionMessage`) hold the model-protocol messages
verbatim -- tool arguments, tool results, reasoning. None of that is user-safe
API surface. This module reduces those rows to per-execution events in
conversation order:

- :class:`ToolCallEvent` -- which tool ran, with what raw payloads, when, and
  whether it succeeded.
- :class:`NarrationEvent` -- assistant prose recorded mid-run, which is what
  lets a long turn read as the agent explaining itself rather than as a
  spinner.

A workflow presenter distills the raw payloads into public fields and drops the
rest; nothing here is shaped for a response body.

Server-side tools (tools the provider ran itself, such as native web search)
are persisted as opaque provider blocks. They are surfaced best-effort from
the shapes the Claude adapter records -- ``server_tool_use`` requests paired
with ``*_tool_result`` blocks -- and an unrecognized shape is skipped rather
than guessed at: the feed is observability, not a replay of the turn.
"""

from dataclasses import dataclass, field
from datetime import datetime

from research_ai.models import AgentConversation, AgentExecutionMessage

_SERVER_RESULT_SUFFIX = "_tool_result"


@dataclass
class ToolCallEvent:
    """One tool call reconstructed from an execution's trace rows.

    Timestamps are trace-row persistence times: they order events, but
    parallel calls issued in one assistant turn share rows, so they must not
    be read as per-call durations.
    """

    tool: str
    input: dict
    started_at: datetime
    server_side: bool = False
    result: dict | None = None
    is_error: bool = False
    finished_at: datetime | None = None

    @property
    def completed(self) -> bool:
        return self.finished_at is not None


@dataclass
class NarrationEvent:
    """Assistant prose from one text block of an assistant trace row.

    ``from_final_turn`` marks text belonging to the execution's *last* assistant
    message. That text is the answer itself -- the same string the chat
    publishes as an assistant message once the run succeeds -- so a presenter
    showing a finished turn must drop it to avoid saying everything twice.
    While a run is still going the flag is meaningless in practice: the last
    assistant message is simply the newest thing the model said, nothing is
    published yet, and showing it is the whole point.

    The distinction cannot be drawn from the block alone. A turn that used the
    provider's own web search puts narration, the server-side call, and the
    final answer in one assistant message, so "did this message make tool
    calls" does not separate prose from answer -- only position does.
    """

    text: str
    at: datetime
    from_final_turn: bool = False


ActivityEvent = ToolCallEvent | NarrationEvent


@dataclass
class _Walk:
    """Pairing state while trace rows stream by in conversation order."""

    events: dict[int, list[ActivityEvent]] = field(default_factory=dict)
    open_calls: dict[tuple[int, str], ToolCallEvent] = field(default_factory=dict)
    # Narration from the newest assistant row seen per execution. It stays here
    # until a later assistant row proves it was not the final turn.
    pending_final: dict[int, list[NarrationEvent]] = field(default_factory=dict)

    def open(self, execution_id: int, call_id, event: ToolCallEvent) -> None:
        self.events.setdefault(execution_id, []).append(event)
        if isinstance(call_id, str) and call_id:
            self.open_calls[(execution_id, call_id)] = event

    def close(
        self,
        execution_id: int,
        call_id,
        *,
        result,
        is_error: bool,
        finished_at: datetime,
    ) -> None:
        if not isinstance(call_id, str):
            return
        event = self.open_calls.pop((execution_id, call_id), None)
        if event is None:
            return
        event.result = result if isinstance(result, dict) else {}
        event.is_error = is_error
        event.finished_at = finished_at

    def begin_assistant_row(self, execution_id: int) -> None:
        """A new assistant row demotes the previous one out of final position."""
        self.pending_final[execution_id] = []

    def narrate(self, execution_id: int, event: NarrationEvent) -> None:
        self.events.setdefault(execution_id, []).append(event)
        self.pending_final.setdefault(execution_id, []).append(event)

    def finish(self) -> dict[int, list[ActivityEvent]]:
        for narrations in self.pending_final.values():
            for event in narrations:
                event.from_final_turn = True
        return self.events


def conversation_activity_events(
    conversation: AgentConversation,
    *,
    execution_ids: list[int] | None = None,
) -> dict[int, list[ActivityEvent]]:
    """Ordered activity events per execution id, from one trace query.

    Tool pairing follows the id-correlation invariant: a ``tool_use`` block's id
    is echoed by its ``tool_result``. A call whose result row never landed --
    the turn is still running, or it crashed or was truncated mid-flight --
    stays uncompleted rather than being guessed at; the presenter decides what
    an open call means from the execution's own status.

    ``execution_ids`` narrows the scan. Trace ``content`` holds whole note
    documents, paper full texts and provider payloads, so walking a whole
    conversation costs more with every turn ever taken on it -- far too much to
    repeat on each poll of a live turn. Since a terminal execution's events can
    never change again, a caller that already has them passes only the ids it
    still needs. An empty list means no rows are read at all.
    """
    rows = AgentExecutionMessage.objects.filter(conversation=conversation).exclude(
        provenance__in=[
            AgentExecutionMessage.Provenance.HUMAN,
            AgentExecutionMessage.Provenance.BACKEND,
        ]
    )
    if execution_ids is not None:
        if not execution_ids:
            return {}
        rows = rows.filter(execution_id__in=execution_ids)
    walk = _Walk()
    for execution_id, role, content, created in rows.order_by("sequence").values_list(
        "execution_id", "role", "content", "created_date"
    ):
        if not isinstance(content, list):
            continue
        if role == "assistant":
            walk.begin_assistant_row(execution_id)
        for block in content:
            if isinstance(block, dict):
                _apply_block(walk, execution_id, block, created, role=role)
    return walk.finish()


def _apply_block(
    walk: _Walk, execution_id: int, block: dict, created: datetime, *, role: str
) -> None:
    block_type = block.get("type")
    if block_type == "tool_use":
        tool_input = block.get("input")
        walk.open(
            execution_id,
            block.get("id"),
            ToolCallEvent(
                tool=str(block.get("name") or ""),
                input=tool_input if isinstance(tool_input, dict) else {},
                started_at=created,
            ),
        )
    elif block_type == "tool_result":
        walk.close(
            execution_id,
            block.get("tool_use_id"),
            result=block.get("content"),
            is_error=bool(block.get("is_error")),
            finished_at=created,
        )
    elif block_type == "server_tool":
        _apply_server_block(walk, execution_id, block.get("data"), created)
    elif block_type == "text" and role == "assistant":
        _apply_text_block(walk, execution_id, block, created)


def _apply_text_block(
    walk: _Walk, execution_id: int, block: dict, created: datetime
) -> None:
    # A row too large to persist is replaced by a marker text block carrying
    # ``_truncated``; that marker is written for an operator reading the trace,
    # not for the user waiting on the turn.
    if block.get("_truncated"):
        return
    text = block.get("text")
    if not isinstance(text, str) or not text.strip():
        return
    walk.narrate(execution_id, NarrationEvent(text=text.strip(), at=created))


def _apply_server_block(
    walk: _Walk, execution_id: int, data, created: datetime
) -> None:
    if not isinstance(data, dict):
        return
    data_type = data.get("type")
    if data_type == "server_tool_use":
        tool_input = data.get("input")
        walk.open(
            execution_id,
            data.get("id"),
            ToolCallEvent(
                tool=str(data.get("name") or ""),
                input=tool_input if isinstance(tool_input, dict) else {},
                started_at=created,
                server_side=True,
            ),
        )
    elif isinstance(data_type, str) and data_type.endswith(_SERVER_RESULT_SUFFIX):
        # A provider reports a failed server call as a single error object
        # where a successful one carries a result list (for example
        # ``web_search_tool_result_error``); that shape is the only error
        # signal these blocks have.
        content = data.get("content")
        is_error = isinstance(content, dict) and str(content.get("type", "")).endswith(
            "_error"
        )
        walk.close(
            execution_id,
            data.get("tool_use_id"),
            result=data,
            is_error=is_error,
            finished_at=created,
        )
