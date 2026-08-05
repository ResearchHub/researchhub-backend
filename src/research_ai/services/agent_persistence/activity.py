"""Tool-call events extracted from persisted execution traces.

Trace rows (:class:`AgentExecutionMessage`) hold the model-protocol messages
verbatim -- tool arguments, tool results, reasoning. None of that is user-safe
API surface. This module reduces those rows to per-execution tool-call events:
which tool ran, with what raw payloads, when, and whether it succeeded. A
workflow presenter distills the raw payloads into public fields and drops the
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
class _Walk:
    """Pairing state while trace rows stream by in conversation order."""

    events: dict[int, list[ToolCallEvent]] = field(default_factory=dict)
    open_calls: dict[tuple[int, str], ToolCallEvent] = field(default_factory=dict)

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


def conversation_tool_events(
    conversation: AgentConversation,
) -> dict[int, list[ToolCallEvent]]:
    """Ordered tool-call events per execution id, from one trace query.

    Pairing follows the id-correlation invariant: a ``tool_use`` block's id is
    echoed by its ``tool_result``. A call whose result row never landed -- the
    turn is still running, or it crashed or was truncated mid-flight -- stays
    uncompleted rather than being guessed at; the presenter decides what an
    open call means from the execution's own status.
    """
    rows = (
        AgentExecutionMessage.objects.filter(conversation=conversation)
        .exclude(
            provenance__in=[
                AgentExecutionMessage.Provenance.HUMAN,
                AgentExecutionMessage.Provenance.BACKEND,
            ]
        )
        .order_by("sequence")
        .values_list("execution_id", "content", "created_date")
    )
    walk = _Walk()
    for execution_id, content, created in rows:
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict):
                _apply_block(walk, execution_id, block, created)
    return walk.events


def _apply_block(
    walk: _Walk, execution_id: int, block: dict, created: datetime
) -> None:
    block_type = block.get("type")
    if block_type == "tool_use":
        input = block.get("input")
        walk.open(
            execution_id,
            block.get("id"),
            ToolCallEvent(
                tool=str(block.get("name") or ""),
                input=input if isinstance(input, dict) else {},
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


def _apply_server_block(
    walk: _Walk, execution_id: int, data, created: datetime
) -> None:
    if not isinstance(data, dict):
        return
    data_type = data.get("type")
    if data_type == "server_tool_use":
        input = data.get("input")
        walk.open(
            execution_id,
            data.get("id"),
            ToolCallEvent(
                tool=str(data.get("name") or ""),
                input=input if isinstance(input, dict) else {},
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
