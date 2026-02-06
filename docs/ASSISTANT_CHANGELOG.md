# Assistant API - Changes from Original Plan

This document summarizes backend changes that diverge from the original build plan. Pass this to the frontend team alongside `ASSISTANT_API.md` for the full spec.

---

## 1. Submit endpoint removed

The `POST /api/assistant/submit/` endpoint no longer exists. The backend does NOT create notes, posts, or grants.

**Frontend is responsible for:**
- Creating notes via the existing note API
- Assembling the final payload from field state
- Calling `POST /api/researchhubpost/` (proposals) or `POST /api/grant/` (RFPs) directly

---

## 2. `note_id` added to sessions

Every chat response now includes a `note_id` field (integer or null).

**How it works:**
- The frontend creates a note using its own note API
- It sends the note ID back to the backend via `structured_input`:
  ```json
  {
    "message": "Note created",
    "structured_input": { "field": "note_id", "value": 365 }
  }
  ```
- From that point, all responses include `note_id: 365`
- The GET session endpoint also returns `note_id`

---

## 3. `is_resume` flag added to chat request

Instead of detecting the string "Resuming session", the backend uses an explicit boolean.

**Request:**
```json
{
  "session_id": "abc-123",
  "message": "Resuming session",
  "is_resume": true
}
```

**Behavior:**
- Message is NOT added to conversation history
- Response is a welcome-back summary with progress info
- Quick replies: "Continue where I left off" / "Start over"

---

## 4. GET session endpoint returns no conversation history

`GET /api/assistant/sessions/{id}/` returns field state, role, note_id, is_complete, and timestamps only. No `messages` array.

**On page refresh, the frontend should:**
1. Call `GET /api/assistant/sessions/{id}/` to hydrate field state and note reference
2. Call `POST /api/assistant/chat/` with `is_resume: true` to get the welcome-back message
3. Chat history is lost on refresh (field state and note persist)

---

## 5. All fields initialized to "empty" on session creation

When a session is created, `field_state` is pre-populated with all fields set to `{"status": "empty", "value": ""}`. The frontend does not need to initialize these.

**Researcher fields:** `title`, `description`, `topic_ids`, `author_ids`, `funding_amount_rsc`, `deadline`, `nonprofit_id`

**Funder fields:** `title`, `description`, `topic_ids`, `funding_amount_rsc`, `deadline`

Field status values: `"empty"`, `"ai_suggested"`, `"complete"`

---

## 6. Field names kept as-is

The field keys are: `topic_ids`, `author_ids`, `nonprofit_id`, `funding_amount_rsc` (not `topics`, `authors`, `nonprofit`, `amount`). These match the original implementation.

---

## 7. Rich editor support added (`input_type: "rich_editor"`)

When the AI drafts a description, the response includes:
- `input_type: "rich_editor"` - triggers the editor panel
- `follow_up` - HTML string for the editor content
- `editor_field` - which field the content maps to (e.g. `"description"`)

When the user confirms edits, send:
```json
{
  "message": "I've finished editing the description.",
  "structured_input": {
    "field": "description",
    "value": "<tiptap JSON string>"
  }
}
```

---

## Summary of endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/assistant/chat/` | Send message, get AI response |
| GET | `/api/assistant/sessions/{id}/` | Get session state (no chat history) |
| GET | `/api/assistant/sessions/` | List user's sessions |
| ~~POST~~ | ~~`/api/assistant/submit/`~~ | **Removed** |

Full API reference: `docs/ASSISTANT_API.md`
