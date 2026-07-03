"""Unit tests for AWS client helpers (client construction only, no network)."""

from django.test import SimpleTestCase, override_settings

from utils.aws import bedrock_runtime_client


class BedrockRuntimeClientTests(SimpleTestCase):
    def test_client_config_has_adaptive_retries_and_timeouts(self):
        # Act
        client = bedrock_runtime_client()

        # Assert: transient throttling is retried instead of killing a run.
        # botocore normalizes max_attempts=8 to total_max_attempts=9 (the
        # initial call plus eight retries).
        config = client.meta.config
        self.assertEqual(config.retries, {"mode": "adaptive", "total_max_attempts": 9})
        self.assertEqual(config.read_timeout, 600)
        self.assertEqual(config.connect_timeout, 60)

    @override_settings(BEDROCK_RUNTIME_MAX_ATTEMPTS=3)
    def test_max_attempts_is_settings_backed(self):
        # Act
        client = bedrock_runtime_client()

        # Assert
        self.assertEqual(client.meta.config.retries["total_max_attempts"], 4)
