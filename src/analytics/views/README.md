# Analytics Views Documentation

## Overview

The analytics module provides webhook endpoints for receiving and processing events from external analytics services like Amplitude.

## Components

### 1. Amplitude Webhook Endpoint (`amplitude_webhook_view.py`)

**URL**: `/webhooks/amplitude/`  
**Method**: POST  
**Purpose**: Receives events from Amplitude and processes them through the EventProcessor

#### Features
- Receives events from Amplitude webhook
- Validates payload structure
- Processes events through EventProcessor
- Handles errors gracefully
- Returns processing statistics

#### Expected Payload Format

```json
{
  "event_type": "click",
  "user_id": "12345",
  "event_properties": {
    "user_id": "12345",
    "related_work.unified_document_id": "doc_123",
    "related_work.content_type": "paper",
    "impression": ["123", "456", "789"]
  },
  "user_properties": {...},
  "time": 1234567890000
}
```

Or for multiple events:

```json
{
  "events": [
    {
      "event_type": "vote_action",
      "event_properties": {
        "user_id": "12345",
        "related_work.unified_document_id": "doc_1",
        "related_work.content_type": "paper"
      },
      "time": 1234567890000
    },
    {
      "event_type": "comment_created",
      "event_properties": {
        "user_id": "12345",
        "related_work.content_type": "paper",
        "related_work.id": "123"
      },
      "time": 1234567891000
    }
  ]
}
```

#### Response Format

**Success Response (200 OK)**:
```json
{
  "message": "Webhook successfully processed",
  "processed": 2,
  "skipped": 0
}
```

**Error Responses**:
- `400 Bad Request`: Invalid JSON or missing event_type
- `500 Internal Server Error`: Processing errors

## Quick Start

### 1. Configure Amplitude Webhook

In Amplitude dashboard:
1. Go to **Settings → Destinations**
2. Add new destination → **Webhook**
3. Set URL: `https://your-domain.com/webhooks/amplitude/`
4. Enable event forwarding
5. Save the webhook

### 2. Test the Endpoint

```bash
curl -X POST http://localhost:8000/webhooks/amplitude/ \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "vote_action",
    "event_properties": {
      "user_id": "12345",
      "related_work.unified_document_id": "doc_123",
      "related_work.content_type": "paper",
      "impression": ["123", "456", "789"]
    },
    "time": 1234567890000
  }'
```

### 3. Run Tests

```bash
# Run all analytics tests
python manage.py test analytics

# Run specific webhook tests
python manage.py test analytics.tests.test_amplitude_webhook

```


## Event Processing

### EventProcessor Service

The `EventProcessor` service handles event processing logic:

- **`should_process_event(event)`**: Determines if an event should be processed (currently returns `True` for all events)
- **`process_event(event)`**: Processes the event and logs it

### Supported Event Types

TODO

### Event Properties

#### `impression` (optional)

An array of unified document IDs that were shown to the user (impressions). This property is extracted from `event_properties.impression` and stored as a pipe-delimited string in the database.

**Format**: Array of strings (unified document IDs)
**Example**: `["123", "456", "789"]`
**Storage**: Converted to pipe-delimited string: `"123|456|789"`

**Notes**:
- If `impression` is missing or not an array, it will be stored as `None`
- Empty arrays result in `None`
- Non-array values are ignored
- Works with all event types (no filtering)

## Troubleshooting

### Common Issues

**Webhook returns 400 Bad Request**:
- Check payload format matches expected structure
- Ensure `event_type` is present in single event payloads
- Verify JSON is valid

**Events not being processed**:
- Check logs for processing errors
- Verify event structure matches expected format
- Ensure user_id is present in event_properties

**High error rates**:
- Check Amplitude webhook configuration
- Verify endpoint URL is correct
- Monitor server logs for detailed error messages

## Summary

✅ **Webhook endpoint**: `/webhooks/amplitude/`  
✅ **Event processing**: Basic logging and validation  
✅ **Error handling**: Comprehensive error responses  
✅ **Testing**: Full test coverage  
✅ **Documentation**: Complete setup and usage guide  

