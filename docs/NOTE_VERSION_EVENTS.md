# Note version events

Contract for reacting to note content changes in the notebook editor —
e.g. refreshing a clean editor or showing a "Reload / Keep mine" conflict
banner when the AI assistant (or anyone else) edits the open note.

Note content is append-only: every save creates a new `NoteContent` version
and repoints `note.latest_version`. Whenever a version row is committed —
editor autosave, agent `edit_note`, or a system writer — the backend emits a
`note_version_created` event on a per-note WebSocket channel.

## WebSocket channel

```
wss://<host>/ws/notebook/notes/<note_id>/
```

- **Auth**: same subprotocol scheme as the other notebook sockets — offer
  `["Token", <auth token>]` as WebSocket subprotocols; the server echoes
  `Token` back on accept.
- **Access**: the note's read permission, exactly as for the note detail
  endpoint (any non-`NO_ACCESS` user- or org-level permission on the note's
  unified document). No editing permission required.
- **Close codes**: `4401` unauthenticated (or deactivated account), `4404`
  note missing, deleted, or not visible to the user (indistinguishable by
  design).

## Event payload

One JSON object per message:

```json
{
  "type": "note_version_created",
  "note_id": 1487,
  "version_id": 5001,
  "parent_version_id": 4998,
  "created_by": 7,
  "created_via": "agent",
  "created_date": "2026-08-12T14:03:22.481923+00:00"
}
```

| Field | Meaning |
| --- | --- |
| `type` | Always `note_version_created` (more note-scoped event types may be added later). |
| `note_id` | The note the version belongs to. |
| `version_id` | Id of the new `NoteContent` row. |
| `parent_version_id` | The version this one was derived from, or `null` when the writer did not report a base (legacy clients, first versions, system writers). |
| `created_by` | User id of the writer, or `null`. |
| `created_via` | `"editor"` (autosave endpoint), `"agent"` (notebook AI tools), `"system"` (programmatic writers, e.g. publish snapshots and proposal imports), or `null` for writers predating attribution. Open-ended: treat unknown values like `"system"`. |
| `created_date` | ISO-8601 timestamp of the version row. |

### Semantics

- **Advisory, at-least-once.** Events carry ids only, never content. Treat
  any event as a nudge to compare version ids and refetch what you need;
  duplicates and reordering must be harmless. The REST API remains the
  source of truth — the socket is a latency optimization, safe to drop.
- **Post-commit.** An event is only emitted after the version's transaction
  commits, so a refetch triggered by an event always sees the version.
- **Own-save recognition.** `POST /api/note_content/` returns the created
  version's `id`; ignore events whose `version_id` matches a save you made.
- **Fast-forward vs conflict.** If an event's `parent_version_id` equals the
  version your editor currently holds, the new version is a clean
  fast-forward of your state (safe to auto-reload). Any other base implies
  a fork worth surfacing.

## REST endpoints

### Save a version (editor autosave)

`POST /api/note_content/` — unchanged, plus one optional field:

- `note` (required): note id.
- `full_json`: the Tiptap document as a JSON-encoded **string**.
- `plain_text`: extracted plain text.
- `full_src`: legacy HTML source (only stored when `full_json` is absent).
- `parent_version` (optional, new): id of the version the editor loaded
  before producing this save. Must be a version of the same note (else
  `400`). Populates `parent_version_id` in events and version history.

Requires editing permission on the note. Responds `200` with the full
serialized version — `id`, `note`, `json`, `plain_text`, `src`,
`created_date`, and the new `created_by` / `created_via` /
`parent_version` fields.

### Fetch one specific version

`GET /api/note_content/<version_id>/`

Returns the same serialized shape as above (`json` / `plain_text` / `src`),
for any version of a note the caller can **read** — editing permission is
not required. Use it to fetch the agent's exact version when newer
autosaves exist, e.g. for the conflict banner's Reload action or a future
version diff view.

## Relationship to chat activity

Agent `edit_note` tool calls also expose `note_version_id` inside the chat
activity payload (`?activity=live` and the chat socket). That linkage is
unchanged and remains the way to correlate a version with a specific chat
conversation; the note channel deliberately omits conversation/execution
ids so it works for every writer, chat-driven or not.
