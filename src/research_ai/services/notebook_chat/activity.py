"""User-safe activity feed for notebook chat turns.

A curated projection of :func:`conversation_tool_events` into a fixed public
shape -- tool, label, status, timestamps -- plus the enrichments the frontend
renders: the note version an edit produced, so an open editor knows to reload,
a human detail line (the search query or author searched for), and title/url
``sources`` for citations. Sources come from every tool that yields citable
items -- web search and the scholarly tools alike -- in one shape, so the
frontend renders one citation list. Raw tool arguments and results never pass
through: tool traffic includes whole note documents, paper full texts, and
provider payloads, and tool error strings are written for the model, not the
user.
"""

from collections.abc import Iterable

from research_ai.services.agent_persistence.activity import ToolCallEvent
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
# The input field per tool whose value is the user's own kind of text -- safe
# and meaningful to echo as the event detail.
_DETAIL_INPUT_FIELDS = {
    WEB_SEARCH: "query",
    SEARCH_INSTITUTIONS: "query",
    SEARCH_AUTHORS: "name",
}
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
    if succeeded:
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
    if not isinstance(items, list):
        return []
    sources = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get(url_field) or "").strip()
        if not url:
            continue
        sources.append({"title": str(item.get("title") or "").strip(), "url": url})
        if len(sources) >= _MAX_SOURCES:
            break
    return sources
