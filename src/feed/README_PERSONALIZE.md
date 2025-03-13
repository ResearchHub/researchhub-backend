# Amazon Personalize Integration for ResearchHub Feed

This document describes the integration of Amazon Personalize with the ResearchHub feed to provide personalized content recommendations to users.

## Overview

Amazon Personalize is a machine learning service that enables developers to create individualized recommendations for users of their applications. This integration uses Amazon Personalize to recommend content in the ResearchHub feed based on user interactions and preferences.

## Setup

### 1. Create Amazon Personalize Resources

Before using the integration, you need to set up the following resources in Amazon Personalize:

1. **Dataset Group**: Create a dataset group to contain your datasets and models.
2. **Schemas**: Define schemas for users, items, and interactions.
3. **Datasets**: Create datasets for users, items, and interactions.
4. **Solution**: Train a recommendation model using your datasets.
5. **Campaign**: Deploy the solution to create a recommendation campaign.

### 2. Export Data

Use the provided management command to export data for Amazon Personalize:

```bash
python manage.py export_data_for_personalize --output-dir=personalize_data
```

This will create three CSV files:
- `users.csv`: Contains user IDs
- `items.csv`: Contains unified document IDs with metadata
- `interactions.csv`: Contains user-item interactions (views, votes)

### 3. Import Data to Amazon Personalize

Upload the exported CSV files to Amazon Personalize datasets using the AWS Console or CLI.

### 4. Configure Django Settings

Add the following settings to your environment or `keys.py` file:

```python
AWS_PERSONALIZE_ENABLED = True
AWS_PERSONALIZE_CAMPAIGN_ARN = "arn:aws:personalize:region:account:campaign/campaign-name"
AWS_PERSONALIZE_TRACKING_ID = "tracking-id"
```

## Usage

### Personalized Feed Endpoint

The personalized feed is available at:

```
GET /api/feed/personalized/
```

This endpoint returns feed entries recommended by Amazon Personalize based on the user's past interactions and preferences.

### Recording Events

The integration automatically records view events when users access the personalized feed. You can also manually record events using the `AmazonPersonalizeService`:

```python
from feed.services import AmazonPersonalizeService

personalize_service = AmazonPersonalizeService()
personalize_service.record_event(
    user=request.user,
    item_id=unified_document_id,
    event_type="view",
    event_value=1,
    session_id=request.session.session_key
)
```

## Maintenance

### Retraining the Model

To keep recommendations relevant, periodically export new data and retrain your Amazon Personalize solution.

### Monitoring

Monitor the performance of your recommendations using Amazon CloudWatch metrics for Amazon Personalize.

## Troubleshooting

- **No Recommendations**: If no recommendations are returned, the system falls back to the popular feed.
- **AWS Credentials**: Ensure that AWS credentials are properly configured with permissions for Amazon Personalize.
- **Logging**: Check the logs for any errors related to Amazon Personalize API calls.
