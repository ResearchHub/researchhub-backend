"""Tests for Expert Finder Gmail bulk send pacing helpers."""

from unittest.mock import patch

from django.test import TestCase

from research_ai.services.outreach.send_pacing import next_bulk_interval_seconds


class SendPacingUnitTests(TestCase):
    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MIN_INTERVAL_SECONDS",
        1500,
    )
    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MAX_INTERVAL_SECONDS",
        1500,
    )
    def test_interval_reads_constants(self):
        self.assertEqual(next_bulk_interval_seconds(), 1500)

    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MIN_INTERVAL_SECONDS",
        1200,
    )
    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MAX_INTERVAL_SECONDS",
        1800,
    )
    def test_next_bulk_interval_in_range(self):
        for _ in range(20):
            wait = next_bulk_interval_seconds()
            self.assertGreaterEqual(wait, 1200)
            self.assertLessEqual(wait, 1800)

    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MIN_INTERVAL_SECONDS",
        0,
    )
    @patch(
        "research_ai.services.outreach.send_pacing.OUTREACH_SEND_MAX_INTERVAL_SECONDS",
        0,
    )
    def test_zero_interval_disables_pacing(self):
        self.assertEqual(next_bulk_interval_seconds(), 0)
