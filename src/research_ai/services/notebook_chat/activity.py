"""User-safe activity feed for notebook chat turns.

A curated projection of :func:`conversation_activity_events` into fixed public
shapes. Tool calls carry tool, label, status and timestamps, plus the
enrichments the frontend renders: the note version an edit produced, so an open
editor knows to reload, a human detail line (the search query or author searched
for), and title/url ``sources`` for citations. Sources come from every tool that
yields citable items -- web search and the scholarly tools alike -- in one
shape, so the frontend renders one citation list. Narration events carry the
prose the model wrote between tool calls, which is what turns a slow turn from a
spinner into a readable account of what the agent is doing.

Raw tool arguments and results never pass through: tool traffic includes whole
note documents, paper full texts, and provider payloads, and tool error strings
are written for the model, not the user.

Alongside the feed, :func:`execution_phase` reduces the same events to a single
coarse "what is it doing right now" for a live turn, so a client has something
to show without interpreting the event list itself.
"""

from collections.abc import Iterable

from research_ai.services.agent_persistence.activity import (
    ActivityEvent,
    NarrationEvent,
    ToolCallEvent,
)
from research_ai.services.note_tools import EDIT_NOTE, READ_NOTE
from research_ai.services.researcher_profile.openalex_tools import GET_WORK_FULLTEXT

WEB_SEARCH = "web_search"
SEARCH_INSTITUTIONS = "search_institutions"
SEARCH_AUTHORS = "search_authors"
GET_AUTHOR = "get_author"
GET_AUTHOR_WORKS = "get_author_works"

_LABELS = {
    READ_NOTE: "Read the note",
    EDIT_NOTE: "Edited the note",
    WEB_SEARCH: "Searched the web",
    SEARCH_INSTITUTIONS: "Searched institutions",
    SEARCH_AUTHORS: "Searched scholarly authors",
    GET_AUTHOR: "Looked up an author",
    GET_AUTHOR_WORKS: "Fetched an author's publications",
    GET_WORK_FULLTEXT: "Read a paper",
}
# What each tool is doing while the call is still open, for the live phase.
# Distinct from _LABELS, which reads as a completed step.
_ACTIVE_LABELS = {
    READ_NOTE: "Reading the note",
    EDIT_NOTE: "Editing the note",
    WEB_SEARCH: "Searching the web",
    SEARCH_INSTITUTIONS: "Searching institutions",
    SEARCH_AUTHORS: "Searching scholarly authors",
    GET_AUTHOR: "Looking up an author",
    GET_AUTHOR_WORKS: "Fetching an author's publications",
    GET_WORK_FULLTEXT: "Reading a paper",
}
# The input field per tool whose value is the user's own kind of text -- safe
# and meaningful to echo as the event detail.
_DETAIL_INPUT_FIELDS = {
    WEB_SEARCH: "query",
    SEARCH_INSTITUTIONS: "query",
    SEARCH_AUTHORS: "name",
}
_MAX_DETAIL_CHARS = 200
_MAX_SOURCES = 5
# Narration between tool calls is a sentence or two in practice. The bound is
# generous enough never to cut real narration, and only exists so one
# pathological turn cannot make every poll of this conversation huge.
_MAX_NARRATION_CHARS = 4000

PHASE_QUEUED = "queued"
PHASE_USING_TOOL = "using_tool"
PHASE_RESPONDING = "responding"
PHASE_THINKING = "thinking"


def public_activity(
    events: Iterable[ActivityEvent],
    *,
    execution_active: bool,
    answer_published: bool,
) -> list[dict]:
    """Render events to the public shapes; nothing raw passes through."""
    public = []
    for event in events:
        if isinstance(event, NarrationEvent):
            rendered = _public_narration(event, answer_published)
        else:
            rendered = _public_tool_call(event, execution_active)
        if rendered is not None:
            public.append(rendered)
    return public


def execution_phase(
    events: Iterable[ActivityEvent],
    *,
    execution_active: bool,
    execution_claimed: bool,
) -> dict | None:
    """What a live turn is doing right now, or ``None`` once it is terminal.

    A turn no worker has claimed yet is ``queued``: nothing is thinking, and
    during a backlog that difference stays visible for a while. Everything
    else is derived rather than stored: the trace rows already say it, and a
    separate persisted phase would be one more thing a dead worker could leave
    lying about the run's state.
    """
    if not execution_active:
        return None
    if not execution_claimed:
        return {"state": PHASE_QUEUED, "label": "Waiting to start"}
    ordered = list(events)
    open_calls = [
        event
        for event in ordered
        if isinstance(event, ToolCallEvent) and not event.completed
    ]
    if len(open_calls) == 1:
        (call,) = open_calls
        return {
            "state": PHASE_USING_TOOL,
            "label": _active_label(call.tool),
            "tool": call.tool,
        }
    if open_calls:
        # One turn can dispatch several calls. They run in their emitted order
        # but their results land as one batch, so mid-batch the trace cannot
        # say which call is the current one -- naming any would be a guess.
        return {"state": PHASE_USING_TOOL, "label": "Running tools"}
    if ordered and isinstance(ordered[-1], NarrationEvent):
        return {"state": PHASE_RESPONDING, "label": "Writing a response"}
    return {"state": PHASE_THINKING, "label": "Thinking"}


def _public_narration(event: NarrationEvent, answer_published: bool) -> dict | None:
    # Once the final assistant text is published as the chat message, echoing
    # it here too would show the answer twice. Until then it stays: on a live
    # turn nothing is published yet, and a turn that fails or is stopped never
    # publishes, leaving the feed as the only account of what the model last
    # said.
    if event.from_final_turn and answer_published:
        return None
    return {
        "type": "narration",
        "text": event.text[:_MAX_NARRATION_CHARS],
        "at": event.at,
    }


def _public_tool_call(event: ToolCallEvent, execution_active: bool) -> dict:
    public = {
        "type": "tool_call",
        "tool": event.tool,
        "label": _label(event.tool),
        "status": _status(event, execution_active),
        "started_at": event.started_at,
        "finished_at": event.finished_at,
    }
    detail = _detail(event)
    if detail:
        public["detail"] = detail
    succeeded = event.completed and not event.is_error
    if succeeded and event.tool == EDIT_NOTE:
        version_id = (event.result or {}).get("version_id")
        if isinstance(version_id, int):
            public["note_version_id"] = version_id
    if succeeded:
        sources = _sources(event)
        if sources:
            public["sources"] = sources
    return public


def _label(tool: str) -> str:
    if tool in _LABELS:
        return _LABELS[tool]
    return f"Used {tool}" if tool else "Ran a tool"


def _active_label(tool: str) -> str:
    if tool in _ACTIVE_LABELS:
        return _ACTIVE_LABELS[tool]
    return f"Running {tool}" if tool else "Running a tool"


def _status(event: ToolCallEvent, execution_active: bool) -> str:
    if not event.completed:
        return "in_progress" if execution_active else "interrupted"
    return "failed" if event.is_error else "succeeded"


def _detail(event: ToolCallEvent) -> str | None:
    field = _DETAIL_INPUT_FIELDS.get(event.tool)
    if field is not None:
        value = event.input.get(field)
    elif event.tool == GET_AUTHOR and event.completed and not event.is_error:
        # The input is an opaque OpenAlex id; the resolved author's name is
        # the human-meaningful part, and it only exists in the result.
        value = (event.result or {}).get("display_name")
    else:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:_MAX_DETAIL_CHARS]


def _sources(event: ToolCallEvent) -> list[dict]:
    """Title/url pairs from any tool whose result carries citable items.

    Web search returns ``{"results": [...]}`` locally and ``{"content":
    [...]}`` when the provider ran it; scholarly works live under ``works``
    with their url in ``source_url``; a full-text read echoes the one paper it
    read. All reduce to the same citation shape, and anything unrecognized
    reduces to nothing.
    """
    result = event.result or {}
    if event.tool == WEB_SEARCH:
        items = result.get("content") if event.server_side else result.get("results")
        url_field = "url"
    elif event.tool == GET_AUTHOR_WORKS:
        items = result.get("works")
        url_field = "source_url"
    elif event.tool == GET_WORK_FULLTEXT:
        items = [result]
        url_field = "source_url"
    else:
        return []
    return _citations(items, url_field)


def _citations(items, url_field: str) -> list[dict]:
    """Reduce result items to at most ``_MAX_SOURCES`` title/url pairs."""
    if not isinstance(items, list):
        return []
    citations = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get(url_field) or "").strip()
        if not url:
            continue
        citations.append({"title": str(item.get("title") or "").strip(), "url": url})
        if len(citations) >= _MAX_SOURCES:
            break
    return citations
