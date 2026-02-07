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

**Author selection (researcher):**
```json
{ "structured_input": { "field": "authors", "value": [142, 387] } }
```

**Topic/Hub selection:**
```json
{ "structured_input": { "field": "hubs", "value": [5, 12, 23] } }
```

**Contact person selection (funder):**
```json
{ "structured_input": { "field": "grant_contacts", "value": [42] } }
```

**Note ID (after frontend creates a note):**
```json
{ "structured_input": { "field": "note_id", "value": 365 } }
```

**Rich editor confirmation:**
```json
{ "structured_input": { "field": "description", "value": "{\"type\":\"doc\",\"content\":[...]}" } }
```

#### Response

```json
{
  "session_id": "297b9b40-...",
  "message": "I've drafted the Summary section. You can view and edit it in the editor.",
  "follow_up": "<h1>Full HTML document</h1>...",
  "input_type": "rich_editor",
  "editor_field": "description",
  "note_id": 365,
  "quick_replies": [
    {"label": "Looks good", "value": "Looks good, let's continue"},
    {"label": "I want to make changes", "value": "I want to make changes to this section"}
  ],
  "field_updates": {
    "title": {"status": "complete", "value": "EMF and Soft Tissue Injury"}
  },
  "complete": false,
  "payload": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | UUID | Session identifier |
| `message` | string | Bot's response to display |
| `follow_up` | string or null | Full HTML document for the editor (when `input_type` is `rich_editor`) |
| `input_type` | string or null | UI component to render (see table below) |
| `editor_field` | string or null | Field name for rich editor content (e.g. `"description"`) |
| `note_id` | integer or null | Note ID associated with this session |
| `quick_replies` | array or null | Suggested response buttons |
| `field_updates` | object or null | Updates to field state |
| `complete` | boolean | `true` when all required fields are collected |
| `payload` | object or null | Final payload (only when `complete` is true) |

#### Input Types

| Value | When | Frontend behavior |
|-------|------|-------------------|
| `null` | Normal conversation, asking questions | Shows the message |
| `"rich_editor"` | AI drafted/updated document content | Shows notification + "View changes" button |
| `"author_lookup"` | Ready to collect authors (researcher) | Shows author search widget |
| `"topic_select"` | Ready to collect topics | Shows topic selector widget |
| `"contact_lookup"` | Ready to collect contact person (funder) | Shows user search widget |
| `"final_review"` | All required fields collected | Shows Submit/Edit buttons |

#### Field Status Values

| Status | Meaning |
|--------|---------|
| `"empty"` | Field has not been touched |
| `"ai_suggested"` | AI generated a value, awaiting user confirmation |
| `"complete"` | User confirmed or explicitly provided |

#### HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success (existing session) |
| 201 | Success (new session created) |
| 400 | Bad request |
| 401 | Unauthorized |
| 404 | Session not found or access denied |

---

### 2. Get Session - `GET /api/assistant/session/<uuid>/`

Retrieve session state. No conversation history — just field state and metadata.

#### Response (200)

```json
{
  "session_id": "297b9b40-...",
  "role": "funder",
  "note_id": 365,
  "field_state": {
    "title": {"status": "complete", "value": "EMF and Soft Tissue Injury"},
    "grant_amount": {"status": "complete", "value": "100000"},
    "grant_end_date": {"status": "empty", "value": ""},
    "grant_organization": {"status": "empty", "value": ""},
    "hubs": {"status": "empty", "value": ""},
    "grant_contacts": {"status": "empty", "value": ""}
  },
  "is_complete": false,
  "created_date": "2026-02-05T22:04:26Z",
  "updated_date": "2026-02-05T22:07:34Z"
}
```

---

### 3. List Sessions - `GET /api/assistant/session/`

List the authenticated user's sessions. Query param: `?limit=10` (max 50).

---

## Form Fields (tracked by progress bar)

### Researcher

| Field | Required | Collected via |
|-------|----------|---------------|
| `title` | Yes | Conversation (AI extracts from Section 1) |
| `authors` | No | UI widget (`author_lookup`) |
| `hubs` | Yes | UI widget (`topic_select`) |

### Funder

| Field | Required | Collected via |
|-------|----------|---------------|
| `title` | Yes | Conversation (AI extracts from Section 1) |
| `grant_amount` | Yes | Conversation (AI extracts from Funding Details) |
| `grant_end_date` | No | Conversation |
| `grant_organization` | No | Conversation |
| `hubs` | Yes | UI widget (`topic_select`) |
| `grant_contacts` | No | UI widget (`contact_lookup`) |

Document content (`description`) is NOT tracked in the progress bar. It is managed entirely through the AI conversation and rich editor.

---

## Frontend Flow

```
1. USER SELECTS ROLE -> "Researcher" or "Funder"

2. FIRST MESSAGE
   POST /api/assistant/chat/ { "role": "funder", "message": "..." }
   -> Save session_id, redirect to /assistant/{session_id}

3. SECTION-BY-SECTION CONVERSATION
   AI asks one question per section -> user answers -> AI drafts section
   -> returns input_type: "rich_editor" with full HTML in follow_up
   -> frontend shows notification "View changes"
   -> quick replies: "Looks good" / "I want to make changes"

4. FORM FIELD COLLECTION
   After document sections: AI triggers UI widgets for remaining fields
   (topic_select, author_lookup, contact_lookup)

5. PAGE REFRESH
   GET /api/assistant/session/{id}/ -> hydrate field state + note_id
   POST /api/assistant/chat/ with is_resume: true -> welcome-back summary

6. SUBMISSION
   Frontend calls existing APIs directly:
   POST /api/researchhubpost/ (proposals) or POST /api/grant/ (RFPs)
```
