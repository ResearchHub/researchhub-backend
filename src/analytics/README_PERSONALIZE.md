# Amplitude Webhook + AWS Personalize Integration

This module implements a comprehensive system for tracking user interactions and generating personalized recommendations using AWS Personalize.

## Architecture Overview

```
┌─────────────┐
│  Amplitude  │ (Frontend tracking)
└──────┬──────┘
       │ Webhook
       ▼
┌─────────────────────┐
│ Django Webhook      │
│ /webhooks/amplitude/│
└──────┬──────────────┘
       │
       ▼
┌─────────────────────┐
│  EventProcessor     │ (Filter & Weight events)
└──────┬──────────────┘
       │
       ├──────────────┐
       │              │
       ▼              ▼
┌──────────────┐  ┌──────────────┐
│   Database   │  │ AWS          │
│   (Storage)  │  │ Personalize  │
└──────────────┘  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ Personalized │
                  │     Feed     │
                  └──────────────┘
```

## Folder Structure

```
src/analytics/
├── views/
│   ├── __init__.py
│   ├── amplitude_webhook_view.py    # Webhook endpoint
│   └── website_visits_view.py       # Existing website visits
├── services/
│   ├── __init__.py
│   ├── event_processor.py           # Event processing & weighting
│   └── personalize_service.py       # AWS Personalize integration
├── tests/
│   ├── __init__.py
│   ├── test_amplitude_webhook.py    # Webhook tests
│   ├── test_event_processor.py      # Processor tests
│   └── test_personalize_service.py  # Service tests
├── models.py                        # Database models (placeholder)
├── serializers.py
├── tasks.py
└── README_PERSONALIZE.md            # This file
```

## Components

### 1. AmplitudeWebhookView (`views/amplitude_webhook_view.py`)
Receives all events from Amplitude via webhook.

**Endpoint**: `POST /webhooks/amplitude/`

**Authentication**: No authentication required

**Payload Example**:
```json
{
  "api_key": "your_api_key",
  "events": [
    {
      "event_type": "click",
      "user_id": "12345",
      "event_properties": {
        "item_id": "doc_123",
        "item_type": "paper"
      },
      "time": 1234567890000
    }
  ]
}
```

### 2. EventProcessor (`services/event_processor.py`)
Processes and weights events based on importance.

**Event Weights**:
- `fundraise/donate`: **3.0** (strongest positive signal)
- `upvote`: **2.0** (explicit support)
- `share`: **2.0** (recommendation to others)
- `bookmark`: **1.8** (save for later)
- `download`: **1.5** (saving resource)
- `comment`: **1.5** (engagement)
- `click`: **1.0** (basic interest)
- `scroll_impression`: **0.7** (confirmed view)
- `view`: **0.5** (passive exposure)
- `initial_impression`: **0.3** (possible view)
- `hide`: **-0.5** (doesn't want to see)
- `not_interested`: **-0.8** (explicit negative)
- `downvote`: **-1.0** (disagreement)
- `flag_content`: **-2.5** (strongest negative signal)

**Filtering Logic**:
- Only processes ML-relevant events
- Requires user_id and item_id
- Differentiates between interactions and impressions

### 3. PersonalizeService (`services/personalize_service.py`)
Interfaces with AWS Personalize for recommendations.

**Methods**:
- `send_interaction_event()`: Send user interactions
- `send_impression_data()`: Send impression data (critical for negative signals)
- `get_recommendations()`: Get personalized recommendations
- `get_similar_items()`: Get similar items

## Database Storage (Future Implementation)

Currently, the system processes events and sends them to AWS Personalize without storing them locally. 

**Future Enhancement**: Add database storage for:
- User interactions (clicks, upvotes, etc.)
- Impression events (what users saw)
- Cached recommendations

This will enable:
- Historical analysis
- Offline processing
- Reduced AWS API calls
- Better debugging and monitoring

**Implementation**: Uncomment the TODO sections in `event_processor.py` and add the models from `models.py` comments.

## Setup Instructions

### 1. Amplitude Webhook Configuration

In Amplitude dashboard:
1. Go to **Settings → Destinations**
2. Add new destination → **Webhook**
3. Set URL: `https://your-domain.com/webhooks/amplitude/`
4. Enable event forwarding
5. Copy the webhook secret

### 2. Environment Variables

Add to your environment:

```bash
# Amplitude
AMPLITUDE_WEBHOOK_SECRET=your_webhook_secret_here

# AWS Personalize
AWS_PERSONALIZE_TRACKING_ID=your_tracking_id
AWS_PERSONALIZE_CAMPAIGN_ARN=arn:aws:personalize:region:account:campaign/campaign-name
AWS_PERSONALIZE_SIMS_CAMPAIGN_ARN=arn:aws:personalize:region:account:campaign/sims-campaign-name
```

### 3. Test the Webhook

```bash
# Test locally
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
# Run all analytics tests
python manage.py test analytics.tests

# Run specific test class
python manage.py test analytics.tests.test_amplitude_webhook

# Run with verbose output
python manage.py test analytics.tests -v 2
```

## Event Weights

The system assigns weights to different events based on importance:

| Event | Weight | Type | Description |
|-------|--------|------|-------------|
| fundraise/donate | 3.0 | Positive | Strongest signal - financial contribution |
| upvote | 2.0 | Positive | Explicit support |
| share | 2.0 | Positive | User recommends to others |
| bookmark | 1.8 | Positive | Save for later |
| download | 1.5 | Positive | Saving resource |
| comment | 1.5 | Positive | Engagement |
| click | 1.0 | Positive | Basic interest |
| scroll_impression | 0.7 | Positive | Confirmed view |
| view | 0.5 | Positive | Passive exposure |
| initial_impression | 0.3 | Positive | Possible view |
| hide | -0.5 | Negative | Doesn't want to see |
| not_interested | -0.8 | Negative | Explicit negative |
| downvote | -1.0 | Negative | Disagreement |
| flag_content | -2.5 | Negative | Strongest negative |

## Frontend Integration Example

```javascript
// Track user click
amplitude.track('click', {
  item_id: document.unifiedDocumentId,
  item_type: 'paper',
  title: document.title
});

// Track feed impression (initial load)
amplitude.track('initial_impression', {
  items_shown: feedItems.map(item => item.id),
  feed_type: 'popular'
});

// Track scroll impression (user scrolled to item)
amplitude.track('scroll_impression', {
  items_shown: [visibleItem.id],
  feed_type: 'popular'
});
```

## Usage in Django

### Get Recommendations for a User

```python
from analytics.services.personalize_service import PersonalizeService

service = PersonalizeService()

# Get personalized recommendations
recommendations = service.get_recommendations(
    user_id='12345',
    num_results=20
)

# recommendations = [
#     {'item_id': 'doc_123', 'score': 0.95},
#     {'item_id': 'doc_456', 'score': 0.87},
#     ...
# ]

# Get similar items
similar = service.get_similar_items(
    item_id='doc_123',
    num_results=10
)
```

### Manual Event Processing

```python
from analytics.services.event_processor import EventProcessor

processor = EventProcessor()

# Process a single event
event = {
    'event_type': 'click',
    'user_id': '12345',
    'event_properties': {
        'item_id': 'doc_123',
        'item_type': 'paper'
    },
    'time': 1234567890000
}

if processor.should_process_event(event):
    processor.process_event(event)
```

## Testing

### Run Tests

```bash
# Run all analytics tests
python manage.py test analytics.tests

# Run specific test class
python manage.py test analytics.tests.test_amplitude_webhook.AmplitudeWebhookTestCase

# Run specific test
python manage.py test analytics.tests.test_event_processor.EventProcessorTestCase.test_event_weights_are_correct
```

### Test Webhook Locally

```bash
curl -X POST http://localhost:8000/webhooks/amplitude/ \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "event_type": "click",
      "user_id": "12345",
      "event_properties": {
        "item_id": "doc_123"
      },
      "time": 1234567890000
    }]
  }'
```

## Monitoring & Analytics

### Key Metrics to Track

1. **Event Processing**:
   - Events received per hour
   - Events processed vs skipped
   - Processing errors

2. **AWS Personalize**:
   - API call latency
   - Recommendation quality (CTR on recommended items)
   - Coverage (% of users with recommendations)

3. **User Engagement**:
   - Click-through rate on recommendations
   - Dwell time on recommended content
   - Conversion rate (upvotes, shares on recommendations)

### Logging

All components use Python logging:

```python
import logging

logger = logging.getLogger(__name__)

# Logs are sent to:
# - Console (development)
# - CloudWatch (production)
# - Sentry (errors)
```

## Troubleshooting

### Webhook Not Receiving Events

1. Check Amplitude destination is enabled
2. Verify webhook URL is correct and accessible
3. Check server logs for processing errors

### Events Not Sent to Personalize

1. Verify AWS credentials are configured
2. Check `AWS_PERSONALIZE_TRACKING_ID` is set
3. Look for errors in logs (Sentry/CloudWatch)
4. Verify event tracker is active in AWS console

### Low Recommendation Quality

1. Ensure sufficient data (AWS Personalize needs minimum interactions)
2. Check impression data is being sent correctly
3. Verify event weights are appropriate for your use case
4. Consider retraining the solution with updated data

## Best Practices

1. **Impression Tracking**: Always send impression data - it's critical for understanding what users saw but didn't interact with.

2. **Event Weighting**: Adjust weights based on your domain. Fundraising might be more important than clicks in academic contexts.

3. **Negative Signals**: Don't ignore negative signals (downvotes, flags). They're important for filtering out unwanted content.

4. **Caching**: When implementing database storage, use the `PersonalizeRecommendation` model to cache results and reduce API costs.

5. **Monitoring**: Set up alerts for webhook failures and AWS Personalize API errors.

## Future Enhancements

1. **Database Storage**: Add local storage for interactions and impressions
2. **Real-time Retraining**: Automatically retrain models when significant data changes occur
3. **A/B Testing**: Test different recommendation algorithms and weights
4. **Context-aware Recommendations**: Include user context (time of day, device, research field)
5. **Hybrid Recommendations**: Combine ML recommendations with editorial picks
6. **Cold Start Solutions**: Better handling for new users/items without interaction history

## Support

For issues or questions:
- Check logs in CloudWatch/Sentry
- Review AWS Personalize documentation: https://docs.aws.amazon.com/personalize/
- Contact the backend team

## License

Internal use only - ResearchHub
