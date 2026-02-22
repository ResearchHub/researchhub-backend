# Backend API Changes

## `GET /api/organization/<slug>/get_organization_notes/`

### New Query Parameters

| Param    | Values                                          | Required | Description                                                                                                         |
|----------|--------------------------------------------------|----------|---------------------------------------------------------------------------------------------------------------------|
| `status` | `DRAFT`, `PUBLISHED`                             | No       | Filter by publish status. `DRAFT` = notes with no associated post. `PUBLISHED` = notes with a post. Omit for all.   |
| `type`   | `GRANT`, `PREREGISTRATION`, `DISCUSSION`, etc.   | No       | Filter by the note's `document_type`. Can be combined with `status` (e.g., `?status=DRAFT&type=GRANT`).             |

### Response Change

Each note object now includes a `document_type` field. It will be `null` for notes created without a type.

```json
{
  "count": 1,
  "results": [
    {
      "id": 123,
      "title": "My Grant Draft",
      "document_type": "GRANT",
      "access": "WORKSPACE",
      "created_date": "...",
      "updated_date": "...",
      "organization": { "..." }
    }
  ]
}
```

---

## `POST /api/note/`

### New Optional Request Body Field

| Field           | Type   | Required | Description                                                                                                  |
|-----------------|--------|----------|--------------------------------------------------------------------------------------------------------------|
| `document_type` | string | No       | One of `DISCUSSION`, `GRANT`, `PREREGISTRATION`, `QUESTION`, etc. If omitted, `document_type` will be `null`. |

### Example Request

```json
{
  "grouping": "WORKSPACE",
  "organization_slug": "my-org",
  "title": "New Grant Draft",
  "document_type": "GRANT"
}
```

### Response Change

The `document_type` field is now included in the note response. This applies to all note serialization endpoints including `GET /api/note/<id>/`.

---

## Unchanged Endpoints

- `GET /api/note/` — list behavior unchanged (no new filters)
- `GET /api/note/<id>/` — `document_type` is now present in the response but no new query params
- All other organization and note endpoints remain unchanged
