# RH Research Assistant API Reference

## Base URL
```
/api/assistant/
```

## Authentication
All endpoints require authentication via token header:
```
Authorization: Token <user_token>
```

---

## Endpoints

### 1. Chat - `POST /api/assistant/chat/`

Main endpoint for conversational interactions with the AI assistant.

#### Request Body

```json
{
  "session_id": "uuid (optional)",
  "role": "researcher | funder",
  "message": "string (required)",
  "structured_input": {
    "field": "string",
    "value": "any"
  },
  "is_resume": false
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | UUID | No | Existing session ID. Omit to create new session. |
| `role` | string | On first message | `"researcher"` or `"funder"`. Required when creating new session. |
| `message` | string | Yes | User's message text |
| `structured_input` | object | No | Data from UI components (see below) |
| `is_resume` | boolean | No | Set `true` to resume a session without adding to history. Returns a progress summary. |

#### Structured Input Examples

When user selects from inline components, send both a human-readable message AND structured data:

**Author selection:**
```json
{
  "message": "I selected Dr. Sarah Chen and Dr. James Wright as co-authors",
  "structured_input": {
    "field": "author_ids",
    "value": [142, 387]
  }
}
```

**Topic/Hub selection:**
```json
{
  "message": "I selected Machine Learning and AI Safety as topics",
  "structured_input": {
    "field": "topic_ids",
    "value": [5, 12, 23]
  }
}
```

**Nonprofit selection:**
```json
{
  "message": "I selected OpenAI Foundation",
  "structured_input": {
    "field": "nonprofit_id",
    "value": "abc123"
  }
}
```

**Note ID (after frontend creates a note):**
```json
{
  "message": "Note created",
  "structured_input": {
    "field": "note_id",
    "value": 365
  }
}
```

**Rich editor confirmation (description edited in Tiptap):**
```json
{
  "session_id": "abc-123",
  "message": "I've finished editing the description.",
  "structured_input": {
    "field": "description",
    "value": "{\"type\":\"doc\",\"content\":[{\"type\":\"heading\",\"attrs\":{\"level\":2},\"content\":[{\"type\":\"text\",\"text\":\"Background\"}]}]}"
  }
}
```

**Resuming a session:**
```json
{
  "session_id": "abc-123",
  "role": "researcher",
  "message": "Resuming session",
  "is_resume": true
}
```

#### Response

```json
{
  "session_id": "297b9b40-90d1-4b85-af0e-8a023aad3115",
  "message": "Bot's conversational response text",
  "follow_up": "Optional HTML content for rich editor or additional formatted content",
  "input_type": "author_lookup | topic_select | nonprofit_lookup | rich_editor | final_review | null",
  "editor_field": "description | null",
  "note_id": 365,
  "quick_replies": [
    {"label": "Short button text", "value": "Full message to send"},
    {"label": "Custom option", "value": null}
  ],
  "field_updates": {
    "title": {"status": "ai_suggested", "value": "Proposed title here"},
    "description": {"status": "complete", "value": "Full description..."}
  },
  "complete": false,
  "payload": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | UUID | Session identifier (save this for subsequent requests) |
| `message` | string | Bot's response to display |
| `follow_up` | string or null | Additional formatted content. When `input_type` is `rich_editor`, this contains the HTML to pre-populate the editor. |
| `input_type` | string or null | Signals which inline component to render (see below) |
| `editor_field` | string or null | When `input_type` is `rich_editor`, names the field the editor content maps to (e.g. `"description"`) |
| `note_id` | integer or null | ID of the note associated with this session |
| `quick_replies` | array or null | Suggested response buttons |
| `field_updates` | object or null | Updates to field state |
| `complete` | boolean | `true` when all required fields are collected |
| `payload` | object or null | Final payload (only when `complete` is true) |

#### Input Types

When `input_type` is non-null, render the corresponding component:

| Value | Component | Description |
|-------|-----------|-------------|
| `author_lookup` | Author autocomplete | Multi-select author search using `/api/search/suggest/?index=author` |
| `topic_select` | Hub/Topic selector | Multi-select from `/api/hub/` |
| `nonprofit_lookup` | Nonprofit search | Search via `/api/organizations/non-profit/search/` |
| `rich_editor` | Rich text editor | Opens split-panel with Tiptap BlockEditor pre-populated with `follow_up` HTML. `editor_field` indicates which field to save to. |
| `final_review` | Review and Submit | Show summary with Submit button |

#### Rich Editor Flow

When `input_type` is `"rich_editor"`:

1. Open a split-panel layout with a Tiptap BlockEditor
2. Pre-populate the editor with the HTML from `follow_up`
3. The user edits the content visually
4. On confirm, send the Tiptap JSON document as `structured_input`:
   - `field`: value of `editor_field` (e.g. `"description"`)
   - `value`: JSON string of the Tiptap document structure

Supported HTML tags in `follow_up`:
`<h1>`, `<h2>`, `<h3>`, `<p>`, `<strong>`, `<em>`, `<ul>`, `<ol>`, `<li>`, `<a>`, `<blockquote>`, `<pre><code>`

#### Resume Flow

When `is_resume` is `true`:

- The message is NOT added to conversation history
- The response contains a welcome-back message summarizing progress
- Quick replies offer "Continue where I left off" and "Start over"

#### Quick Replies

- Display as tappable buttons below bot message
- When `value` is a string: send that string as the next message
- When `value` is `null`: focus the text input for custom entry
- Hide quick replies after user sends any message
- Not shown when `input_type` is `rich_editor`

#### Field Updates

Track these to show progress. Status values:
- `"empty"` - Not yet collected
- `"ai_suggested"` - AI generated a value, awaiting user confirmation
- `"complete"` - User confirmed or explicitly provided

#### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success (existing session) |
| 201 | Success (new session created) |
| 400 | Bad request (missing required fields) |
| 401 | Unauthorized (invalid/missing token) |
| 404 | Session not found or access denied |

---

### 2. Get Session - `GET /api/assistant/sessions/<uuid>/`

Retrieve session state. Returns field state and metadata only, no conversation history.
Only the session creator can access it. Use this to hydrate the UI on page load (e.g. `/assistant/{id}`).

#### Response (200)

```json
{
  "session_id": "297b9b40-90d1-4b85-af0e-8a023aad3115",
  "role": "researcher",
  "note_id": 365,
  "field_state": {
    "title": {"status": "complete", "value": "Gut Microbiome and Autoimmune Disease"},
    "description": {"status": "ai_suggested", "value": "A study investigating..."},
    "topic_ids": {"status": "complete", "value": [5, 12]},
    "author_ids": {"status": "empty", "value": ""},
    "funding_amount_rsc": {"status": "empty", "value": ""},
    "deadline": {"status": "empty", "value": ""},
    "nonprofit_id": {"status": "empty", "value": ""}
  },
  "is_complete": false,
  "created_date": "2026-02-05T22:04:26Z",
  "updated_date": "2026-02-05T22:07:34Z"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | UUID | Session identifier |
| `role` | string | `"researcher"` or `"funder"` |
| `note_id` | integer or null | ID of the note associated with this session |
| `field_state` | object | Current state of all fields (see Initial Fields below) |
| `is_complete` | boolean | Whether all required fields are collected |
| `created_date` | datetime | When the session was created |
| `updated_date` | datetime | When the session was last updated |

**Note:** Conversation history is NOT returned. If the user refreshes, they lose the chat messages but all field state and the note reference persist. Use `is_resume: true` on the chat endpoint to get a welcome-back message.

#### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 401 | Unauthorized |
| 404 | Session not found or belongs to another user |

---

### 3. List Sessions - `GET /api/assistant/sessions/`

List the authenticated user's sessions. Only returns sessions belonging to the requesting user.

#### Query Parameters

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | integer | 10 | Max sessions to return (max 50) |

#### Response (200)

```json
[
  {
    "session_id": "297b9b40-90d1-4b85-af0e-8a023aad3115",
    "role": "researcher",
    "note_id": 365,
    "is_complete": false,
    "message_count": 6,
    "created_date": "2026-02-05T22:04:26Z",
    "updated_date": "2026-02-05T22:07:34Z"
  }
]
```

#### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 401 | Unauthorized |

---

## Initial Field State

When a session is created, all fields are initialized to `{"status": "empty", "value": ""}`.

### Researcher Fields

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Min 20 characters |
| `description` | Yes | Min 50 characters, rich text |
| `topic_ids` | Yes | At least 1 hub/topic |
| `author_ids` | No | Co-authors |
| `funding_amount_rsc` | No | Amount of RSC funding |
| `deadline` | No | Target completion date |
| `nonprofit_id` | No | Associated non-profit |

### Funder Fields

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Grant title |
| `description` | Yes | Requirements and details |
| `topic_ids` | Yes | Eligible research areas |
| `funding_amount_rsc` | Yes | Funding amount |
| `deadline` | No | Application deadline |

---

## Existing APIs for Inline Components

### Author Search
```
GET /api/search/suggest/?q=<query>&index=author,user&limit=10
```

### Hub/Topic List
```
GET /api/hub/?search=<query>&exclude_journals=true
```

### Nonprofit Search
```
GET /api/organizations/non-profit/search/?searchTerm=<query>&count=15
```

---

## Frontend Flow

```
1. USER SELECTS ROLE
   - "Researcher" or "Funder"

2. FIRST MESSAGE
   POST /api/assistant/chat/
   { "role": "researcher", "message": "I have an idea..." }
   -> Save session_id from response
   -> Redirect to /assistant/{session_id}

3. CONVERSATION LOOP
   - Display message + quick_replies
   - User can: tap quick reply, type message, or use inline component
   - POST /api/assistant/chat/ with session_id + message (+ structured_input)
   - Merge field_updates into local field state
   - Repeat until complete === true

4. PAGE REFRESH / RESUME
   GET /api/assistant/sessions/{session_id}/
   -> Hydrate field state, note_id, role
   POST /api/assistant/chat/ with is_resume: true
   -> Get welcome-back message with progress summary

5. NOTE CREATION
   Frontend creates note via existing note API
   POST /api/assistant/chat/ with structured_input: { field: "note_id", value: 365 }

6. SUBMISSION
   Frontend assembles payload and calls existing APIs directly:
   - POST /api/researchhubpost/ for proposals
   - POST /api/grant/ for RFPs
```

---

## Example Session

```bash
# 1. Start conversation
curl -X POST /api/assistant/chat/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"role": "researcher", "message": "I want to research AI safety"}'

# Response includes session_id + note_id: null

# 2. Continue conversation
curl -X POST /api/assistant/chat/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc-123", "message": "I like the alignment angle"}'

# 3. Associate a note
curl -X POST /api/assistant/chat/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "abc-123",
    "message": "Note created",
    "structured_input": {"field": "note_id", "value": 365}
  }'

# 4. Select topics
curl -X POST /api/assistant/chat/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "abc-123",
    "message": "Selected AI Safety and Machine Learning",
    "structured_input": {"field": "topic_ids", "value": [5, 12]}
  }'

# 5. Get session state (e.g. on page refresh)
curl -X GET /api/assistant/sessions/abc-123/ \
  -H "Authorization: Token <token>"

# 6. Resume session
curl -X POST /api/assistant/chat/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc-123", "message": "Resuming session", "is_resume": true}'
```
