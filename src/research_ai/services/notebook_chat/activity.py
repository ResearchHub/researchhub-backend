"""User-safe activity feed for notebook chat turns.

A curated projection of :func:`conversation_tool_events` into a fixed public
shape -- tool, label, status, timestamps -- plus the two enrichments the
frontend renders: the note version an edit produced, so an open editor knows
to reload, and the sources a web search returned, so answers can carry
citations. Raw tool arguments and results never pass through: tool traffic
includes whole note documents and provider payloads, and tool error strings
are written for the model, not the user.
"""

from collections.abc import Iterable

from research_ai.services.agent_persistence.activity import ToolCallEvent
from research_ai.services.note_tools import EDIT_NOTE, READ_NOTE

WEB_SEARCH = "web_search"

_LABELS = {
    READ_NOTE: "Read the note",
    EDIT_NOTE: "Edited the note",
    WEB_SEARCH: "Searched the web",
    "search_institutions": "Searched institutions",
    "search_authors": "Searched scholarly authors",
    "get_author": "Looked up an author",
    "get_author_works": "Fetched an author's publications",
}
# Tools whose ``query`` argument is the user's own kind of text -- safe and
# meaningful to echo as the event detail.
_QUERY_TOOLS = frozenset({WEB_SEARCH, "search_institutions", "search_authors"})
_MAX_DETAIL_CHARS = 200
_MAX_SOURCES = 5


def public_activity(
    events: Iterable[ToolCallEvent], *, execution_active: bool
) -> list[dict]:
    """Render events to the public shape; nothing raw passes through."""
    return [_public_event(event, execution_active) for event in events]


def _public_event(event: ToolCallEvent, execution_active: bool) -> dict:
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
    if succeeded and event.tool == WEB_SEARCH:
        sources = _sources(event)
        if sources:
            public["sources"] = sources
    return public


def _label(tool: str) -> str:
    if tool in _LABELS:
        return _LABELS[tool]
    return f"Used {tool}" if tool else "Ran a tool"


def _status(event: ToolCallEvent, execution_active: bool) -> str:
    if not event.completed:
        return "in_progress" if execution_active else "interrupted"
    return "failed" if event.is_error else "succeeded"


def _detail(event: ToolCallEvent) -> str | None:
    if event.tool not in _QUERY_TOOLS:
        return None
    query = event.input.get("query")
    if not isinstance(query, str) or not query.strip():
        return None
    return query.strip()[:_MAX_DETAIL_CHARS]


def _sources(event: ToolCallEvent) -> list[dict]:
    """Title/url pairs from a web search result, local or server-side.

    The local tool returns ``{"results": [{"title", "url", ...}]}``; the
    provider-run tool wraps its result blocks in ``{"content": [...]}``. Both
    reduce to the same citation shape, and anything unrecognized reduces to
    nothing.
    """
    result = event.result or {}
    items = result.get("content") if event.server_side else result.get("results")
    if not isinstance(items, list):
        return []
    sources = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        sources.append({"title": str(item.get("title") or "").strip(), "url": url})
        if len(sources) >= _MAX_SOURCES:
            break
    return sources
