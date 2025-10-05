# Quick Setup Guide - Amplitude Webhook & AWS Personalize

## Overview

This integration tracks user interactions from Amplitude and prepares data for AWS Personalize to generate personalized content recommendations.

## File Structure

```
src/analytics/
├── views/                           # All view endpoints
│   ├── amplitude_webhook_view.py   # Receives events from Amplitude
│   └── website_visits_view.py      # Existing website visits
├── services/                       # Business logic services
│   ├── event_processor.py         # Event processing & weighting
│   └── personalize_service.py     # AWS Personalize integration
├── tests/                          # Test suite
│   ├── test_amplitude_webhook.py  # Webhook tests
│   ├── test_event_processor.py    # Processor tests
│   └── test_personalize_service.py # AWS service tests
├── models.py                       # Database models (placeholder)
└── README_PERSONALIZE.md           # Full documentation
```

## Key Components

### 1. Webhook Endpoint (`views/amplitude_webhook_view.py`)
- **URL**: `/webhooks/amplitude/`
- **Method**: POST
- Receives events from Amplitude
- Processes and filters events
- Handles errors gracefully

### 2. Event Processor (`services/event_processor.py`)
- Filters ML-relevant events
- Assigns weights to events (3.0 to -2.5)
- Sends to AWS Personalize (when configured)
- TODO: Database storage (future enhancement)

**Event Weights**:
- Fundraise/Donate: **3.0** (strongest positive)
- Upvote/Share: **2.0**
- Download: **1.5**
- Click: **1.0**
- Impressions: **0.3-0.7**
- Downvote: **-1.0**
- Flag: **-2.5** (strongest negative)

### 3. AWS Personalize Service (`services/personalize_service.py`)
- Sends interaction events to AWS
- Sends impression data (what users saw)
- Retrieves recommendations
- Gets similar items

## Quick Start

### 1. Configure Amplitude Webhook

In Amplitude dashboard:
1. Go to **Settings → Destinations**
2. Add new destination → **Webhook**
3. Set URL: `https://your-domain.com/webhooks/amplitude/`
4. Enable event forwarding
5. Save the webhook

### 2. Environment Variables

Add to your environment:

```bash
# AWS Personalize (optional)
AWS_PERSONALIZE_TRACKING_ID=your_tracking_id
AWS_PERSONALIZE_CAMPAIGN_ARN=arn:aws:personalize:region:account:campaign/name
AWS_PERSONALIZE_SIMS_CAMPAIGN_ARN=arn:aws:personalize:region:account:campaign/sims-name
```

### 3. Test the Endpoint

```bash
curl -X POST http://localhost:8000/webhooks/amplitude/ \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "event_type": "click",
      "user_id": "1",
      "event_properties": {
        "item_id": "doc_123"
      },
      "time": 1234567890000
    }]
  }'
```

Expected response:
```json
{
  "message": "Webhook successfully processed",
  "processed": 1,
  "skipped": 0
}
```

### 4. Run Tests

```bash
python manage.py test analytics.tests
```

## Frontend Integration

### Track Click Event

```javascript
amplitude.track('click', {
  item_id: 'unified_doc_123',
  item_type: 'paper',
  title: 'Paper Title'
});
```

### Track Initial Impression

```javascript
// When feed loads with 20 items
amplitude.track('initial_impression', {
  items_shown: ['doc_1', 'doc_2', ..., 'doc_20'],
  feed_type: 'popular'
});
```

### Track Scroll Impression

```javascript
// When user scrolls and sees more items
amplitude.track('scroll_impression', {
  items_shown: ['doc_21', 'doc_22', 'doc_23'],
  feed_type: 'popular'
});
```

## Database Storage (Future Enhancement)

Currently, the system processes events and sends them to AWS Personalize without storing them locally.

**Future Enhancement**: Add database storage for:
- User interactions (clicks, upvotes, etc.)
- Impression events (what users saw)
- Cached recommendations

**Implementation**: Uncomment the TODO sections in `event_processor.py` and add the models from `models.py` comments.

## Usage Examples

### Get Recommendations

```python
from analytics.services.personalize_service import PersonalizeService

service = PersonalizeService()
recommendations = service.get_recommendations(
    user_id='12345',
    num_results=20
)
```

### Process Event Manually

```python
from analytics.services.event_processor import EventProcessor

processor = EventProcessor()
event = {
    'event_type': 'click',
    'user_id': '12345',
    'event_properties': {'item_id': 'doc_123'},
    'time': 1234567890000
}

if processor.should_process_event(event):
    processor.process_event(event)
```

## Monitoring

### Key Metrics
- Events received per hour
- Events processed vs skipped
- Processing errors
- AWS Personalize API latency

### Logging
- Console (development)
- CloudWatch (production)
- Sentry (errors)

## Troubleshooting

### Webhook returns 400
- Check payload format matches expected structure
- Ensure `events` array is present and not empty


### Events not being processed
- Check logs for errors
- Verify user_id exists in database
- Ensure item_id is present in event_properties

## Next Steps

1. **Configure Amplitude** - Set up the webhook destination
2. **Test locally** - Use curl or Postman to test the endpoint
3. **Deploy** - Deploy to staging/production
4. **Monitor** - Check logs for events being processed
5. **AWS Personalize** - Set up when ready for ML recommendations
6. **Database Storage** - Implement when needed for historical analysis

## Summary

✅ Webhook endpoint: `/webhooks/amplitude/`
✅ Event weighting system: 3.0 to -2.5
✅ Positive signals: Click, upvote, share, fundraise
✅ Negative signals: Downvote, flag, hide
✅ Impression tracking: Initial vs scroll impressions
✅ AWS Personalize integration ready
✅ Error handling: Comprehensive logging
✅ Testing: 50+ test cases
✅ Documentation: 3 detailed docs

**Status**: ✅ Ready for deployment (database storage as future enhancement)
