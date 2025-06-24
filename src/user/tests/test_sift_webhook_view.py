import hmac
import json
from hashlib import sha1
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase

from user.models import User


class SiftWebhookViewTests(APITestCase):

    webhook_secret = "sift_test_secret_key"

    def setUp(self):
        self.user = User.objects.create(
            email="test@researchhub.com.com", first_name="Test", last_name="User"
        )

        self.probable_spammer_payload = {
            "decision": {"id": "mark_as_probable_spammer_content_abuse"},
            "entity": {"id": str(self.user.id)},
        }

        self.suspend_user_payload = {
            "decision": {"id": "suspend_user_content_abuse"},
            "entity": {"id": str(self.user.id)},
        }

        self.unknown_decision_payload = {
            "decision": {"id": "unknown_decision_type"},
            "entity": {"id": str(self.user.id)},
        }

    def create_signature(self, body, secret_key):
        """
        Helper method to create valid Sift webhook signature
        """
        key = secret_key.encode("utf-8")
        if isinstance(body, str):
            body = body.encode("utf-8")
        h = hmac.new(key, body, sha1)
        return f"sha1={h.hexdigest()}"

    @override_settings(SIFT_WEBHOOK_SECRET_KEY=webhook_secret)
    def test_webhook_without_signature_returns_401(self):
        """
        Test that webhook without signature header returns 401
        """
        # Arrange
        body = json.dumps(self.probable_spammer_payload)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    @override_settings(SIFT_WEBHOOK_SECRET_KEY=webhook_secret)
    def test_webhook_with_invalid_signature_returns_401(self):
        """
        Test that webhook with invalid signature returns 401
        """
        # Arrange
        body = json.dumps(self.probable_spammer_payload)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": "sha1=invalid_signature"},
        )

        # Assert
        self.assertEqual(response.status_code, 401)

    @patch("utils.siftscience.client")
    @override_settings(SIFT_WEBHOOK_SECRET_KEY=webhook_secret)
    def test_webhook_with_valid_signature_probable_spammer(self, mock_sift_client):
        """
        Test webhook correctly processes probable spammer decision
        """
        # Arrange
        body = json.dumps(self.probable_spammer_payload)
        signature = self.create_signature(body, self.webhook_secret)

        # Verify user is not initially flagged as probable spammer
        self.assertFalse(self.user.probable_spammer)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": signature},
        )

        # Assert
        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.user.probable_spammer)
        self.assertIsNotNone(self.user.spam_updated_date)

    @patch("utils.siftscience.client")
    @override_settings(SIFT_WEBHOOK_SECRET_KEY=webhook_secret)
    def test_webhook_with_valid_signature_suspend_user(self, mock_sift_client):
        """
        Test webhook correctly processes suspend user decision
        """
        # Arrange
        body = json.dumps(self.suspend_user_payload)
        signature = self.create_signature(body, self.webhook_secret)

        # Verify user is not initially suspended or inactive
        self.assertFalse(self.user.is_suspended)
        self.assertTrue(self.user.is_active)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": signature},
        )

        # Assert
        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.user.is_suspended)
        self.assertFalse(self.user.is_active)
        self.assertIsNotNone(self.user.suspended_updated_date)

    @patch("utils.siftscience.client")
    @override_settings(SIFT_WEBHOOK_SECRET_KEY=webhook_secret)
    def test_webhook_with_unknown_decision_does_nothing(self, mock_sift_client):
        """
        Test webhook with unknown decision type doesn't modify user
        """
        # Arrange
        body = json.dumps(self.unknown_decision_payload)
        signature = self.create_signature(body, self.webhook_secret)

        initial_probable_spammer = self.user.probable_spammer
        initial_is_suspended = self.user.is_suspended
        initial_is_active = self.user.is_active

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": signature},
        )

        # Assert
        self.user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        # User state should remain unchanged
        self.assertEqual(self.user.probable_spammer, initial_probable_spammer)
        self.assertEqual(self.user.is_suspended, initial_is_suspended)
        self.assertEqual(self.user.is_active, initial_is_active)

    @patch("utils.siftscience.client")
    @override_settings(
        SIFT_WEBHOOK_SECRET_KEY=webhook_secret,
        EMAIL_WHITELIST=["moderator@researchhub.com.com"],
    )
    def test_webhook_skips_processing_for_moderator(self, mock_sift_client):
        """
        Test webhook skips processing for users who are moderators
        """
        # Arrange
        moderator_user = User.objects.create(
            email="moderator@researchhub.com.com",
            first_name="Moderator",
            last_name="User",
            moderator=True,
        )

        payload = {
            "decision": {"id": "mark_as_probable_spammer_content_abuse_123"},
            "entity": {"id": str(moderator_user.id)},
        }

        body = json.dumps(payload)
        signature = self.create_signature(body, self.webhook_secret)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": signature},
        )

        # Assert
        moderator_user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        # Moderator should not be flagged as probable spammer
        self.assertFalse(moderator_user.probable_spammer)

    @patch("utils.siftscience.client")
    @override_settings(
        SIFT_WEBHOOK_SECRET_KEY=webhook_secret,
        EMAIL_WHITELIST=["whitelist@researchhub.com.com"],
    )
    def test_webhook_skips_processing_for_email_whitelist(self, mock_sift_client):
        """
        Test webhook skips processing for users in EMAIL_WHITELIST
        """
        # Arrange
        whitelisted_user = User.objects.create(
            email="whitelist@researchhub.com.com",
            first_name="Whitelisted",
            last_name="User",
        )

        payload = {
            "decision": {"id": "mark_as_probable_spammer_content_abuse_123"},
            "entity": {"id": str(whitelisted_user.id)},
        }

        body = json.dumps(payload)
        signature = self.create_signature(body, self.webhook_secret)

        # Act
        response = self.client.post(
            "/webhooks/sift/",
            body,
            content_type="application/json",
            headers={"X-Sift-Science-Signature": signature},
        )

        # Assert
        whitelisted_user.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        # Whitelisted user should not be flagged as probable spammer
        self.assertFalse(whitelisted_user.probable_spammer)

    @patch("utils.siftscience.client")
    @override_settings(
        SIFT_WEBHOOK_SECRET_KEY=webhook_secret, SIFT_MODERATION_WHITELIST=[999]
    )
    def test_webhook_skips_processing_for_sift_moderation_whitelist(
        self, mock_sift_client
    ):
        """
        Test webhook skips processing for users in SIFT_MODERATION_WHITELIST
        """
        # Arrange
        whitelisted_user = User.objects.create(
            email="sift_whitelist_unique@researchhub.com.com",
            first_name="SiftWhitelisted",
            last_name="User",
        )

        with self.settings(SIFT_MODERATION_WHITELIST=[whitelisted_user.id]):
            payload = {
                "decision": {"id": "mark_as_probable_spammer_content_abuse_123"},
                "entity": {"id": str(whitelisted_user.id)},
            }

            body = json.dumps(payload)
            signature = self.create_signature(body, self.webhook_secret)

            # Act
            response = self.client.post(
                "/webhooks/sift/",
                body,
                content_type="application/json",
                headers={"X-Sift-Science-Signature": signature},
            )

            # Assert
            whitelisted_user.refresh_from_db()
            self.assertEqual(response.status_code, 200)
            # User in SIFT_MODERATION_WHITELIST should not be flagged as probable
            # spammer
            self.assertFalse(whitelisted_user.probable_spammer)
