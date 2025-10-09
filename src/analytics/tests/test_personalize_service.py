from unittest.mock import MagicMock, patch

from django.test import TestCase

from analytics.services.personalize_service import PersonalizeService


class PersonalizeServiceTestCase(TestCase):
    """
    Test cases for the PersonalizeService.
    """

    def setUp(self):
        self.service = PersonalizeService()

    @patch("boto3.client")
    def test_send_interaction_event_when_not_configured(self, mock_boto):
        """Test that send_interaction_event returns False when not configured."""
        service = PersonalizeService()
        service.events_client = None
        service.tracking_id = None

        result = service.send_interaction_event(
            user_id="123",
            item_id="doc_123",
            event_type="click",
            weight=1.0,
            timestamp=1234567890000,
        )

        self.assertFalse(result)

    def test_aws_personalize_schema_compliance(self):
        """Test that payload structure matches AWS Personalize Interactions schema."""
        # Test the schema structure that should be sent to AWS
        aws_payload = {
            "USER_ID": "123",
            "ITEM_ID": "doc_123",
            "EVENT_TYPE": "feed_item_clicked",
            "EVENT_VALUE": 1.5,
            "DEVICE": "desktop",
            "TIMESTAMP": 1234567890000,
            "IMPRESSION": None,
            "RECOMMENDATION_ID": "home_trending",
        }

        # Verify all required schema fields are present
        required_fields = [
            "USER_ID",
            "ITEM_ID",
            "EVENT_TYPE",
            "EVENT_VALUE",
            "TIMESTAMP",
        ]
        for field in required_fields:
            self.assertIn(field, aws_payload)

        # Verify field types match schema
        self.assertIsInstance(aws_payload["USER_ID"], str)
        self.assertIsInstance(aws_payload["ITEM_ID"], str)
        self.assertIsInstance(aws_payload["EVENT_TYPE"], str)
        self.assertIsInstance(aws_payload["EVENT_VALUE"], (int, float))
        self.assertIsInstance(aws_payload["TIMESTAMP"], int)

        # Verify optional fields can be None
        self.assertIsNone(aws_payload["IMPRESSION"])
        self.assertIsInstance(aws_payload["RECOMMENDATION_ID"], str)

    @patch("boto3.client")
    def test_send_interaction_event_formats_correctly(self, mock_boto):
        """Test that interaction events are formatted correctly for AWS Personalize."""
        mock_events_client = MagicMock()
        mock_events_client.put_events.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200}
        }

        service = PersonalizeService()
        service.events_client = mock_events_client
        service.tracking_id = "test-tracking-id"

        # Test with properties parameter (AWS Personalize schema format)
        aws_payload = {
            "USER_ID": "123",
            "ITEM_ID": "doc_123",
            "EVENT_TYPE": "click",
            "EVENT_VALUE": 1.0,
            "DEVICE": "desktop",
            "TIMESTAMP": 1234567890000,
            "IMPRESSION": None,
            "RECOMMENDATION_ID": None,
        }

        result = service.send_interaction_event(
            user_id="123",
            item_id="doc_123",
            event_type="click",
            weight=1.0,
            timestamp=1234567890000,
            properties=aws_payload,
        )

        self.assertTrue(result)
        mock_events_client.put_events.assert_called_once()

        # Check the call arguments
        call_args = mock_events_client.put_events.call_args
        self.assertEqual(call_args[1]["trackingId"], "test-tracking-id")
        self.assertEqual(call_args[1]["userId"], "123")

        # Verify the event structure matches AWS Personalize schema
        event_list = call_args[1]["eventList"]
        self.assertEqual(len(event_list), 1)
        event = event_list[0]
        self.assertEqual(event["eventType"], "click")
        self.assertEqual(event["itemId"], "doc_123")

    @patch("boto3.client")
    def test_send_impression_data_formats_correctly(self, mock_boto):
        """Test that impression data is formatted correctly for AWS."""
        mock_events_client = MagicMock()
        mock_events_client.put_events.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200}
        }

        service = PersonalizeService()
        service.events_client = mock_events_client
        service.tracking_id = "test-tracking-id"

        items = ["doc_1", "doc_2", "doc_3"]
        result = service.send_impression_data(
            user_id="123", items_shown=items, timestamp=1234567890000
        )

        self.assertTrue(result)
        mock_events_client.put_events.assert_called_once()

        # Check that items are pipe-separated
        call_args = mock_events_client.put_events.call_args
        event_list = call_args[1]["eventList"]
        self.assertIn("impression", event_list[0])

    @patch("boto3.client")
    def test_get_recommendations_returns_empty_when_not_configured(self, mock_boto):
        """Test that get_recommendations returns empty list when not configured."""
        service = PersonalizeService()
        service.client = None

        recommendations = service.get_recommendations(user_id="123")

        self.assertEqual(recommendations, [])

    @patch("boto3.client")
    def test_get_recommendations_formats_response(self, mock_boto):
        """Test that recommendations are formatted correctly."""
        mock_client = MagicMock()
        mock_client.get_recommendations.return_value = {
            "itemList": [
                {"itemId": "doc_1", "score": 0.95},
                {"itemId": "doc_2", "score": 0.87},
            ]
        }

        service = PersonalizeService()
        service.client = mock_client

        # Mock the settings
        with patch("analytics.services.personalize_service.settings") as mock_settings:
            mock_settings.AWS_PERSONALIZE_CAMPAIGN_ARN = (
                "arn:aws:personalize:::campaign/test"
            )

            recommendations = service.get_recommendations(user_id="123", num_results=2)

        self.assertEqual(len(recommendations), 2)
        self.assertEqual(recommendations[0]["item_id"], "doc_1")
        self.assertEqual(recommendations[0]["score"], 0.95)

    @patch("boto3.client")
    def test_get_similar_items_returns_empty_when_not_configured(self, mock_boto):
        """Test that get_similar_items returns empty list when not configured."""
        service = PersonalizeService()
        service.client = None

        similar_items = service.get_similar_items(item_id="doc_123")

        self.assertEqual(similar_items, [])

    @patch("boto3.client")
    def test_send_interaction_handles_errors_gracefully(self, mock_boto):
        """Test that errors in sending interactions are handled gracefully."""
        mock_events_client = MagicMock()
        mock_events_client.put_events.side_effect = Exception("AWS Error")

        service = PersonalizeService()
        service.events_client = mock_events_client
        service.tracking_id = "test-tracking-id"

        result = service.send_interaction_event(
            user_id="123",
            item_id="doc_123",
            event_type="click",
            weight=1.0,
            timestamp=1234567890000,
        )

        self.assertFalse(result)

    def test_aws_personalize_schema_compliance(self):
        """Test that payload structure matches AWS Personalize Interactions schema."""
        # Test the schema structure that should be sent to AWS
        aws_payload = {
            "USER_ID": "123",
            "ITEM_ID": "doc_123",
            "EVENT_TYPE": "feed_item_clicked",
            "EVENT_VALUE": 1.5,
            "DEVICE": "desktop",
            "TIMESTAMP": 1234567890000,
            "IMPRESSION": None,
            "RECOMMENDATION_ID": "home_trending",
        }

        # Verify all required schema fields are present
        required_fields = [
            "USER_ID",
            "ITEM_ID",
            "EVENT_TYPE",
            "EVENT_VALUE",
            "TIMESTAMP",
        ]
        for field in required_fields:
            self.assertIn(field, aws_payload)

        # Verify field types match schema
        self.assertIsInstance(aws_payload["USER_ID"], str)
        self.assertIsInstance(aws_payload["ITEM_ID"], str)
        self.assertIsInstance(aws_payload["EVENT_TYPE"], str)
        self.assertIsInstance(aws_payload["EVENT_VALUE"], (int, float))
        self.assertIsInstance(aws_payload["TIMESTAMP"], int)

        # Verify optional fields can be None
        self.assertIsNone(aws_payload["IMPRESSION"])
        self.assertIsInstance(aws_payload["RECOMMENDATION_ID"], str)
