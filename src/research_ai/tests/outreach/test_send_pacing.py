"""Tests for Expert Finder Gmail bulk send pacing helpers."""

from django.test import TestCase, override_settings

from research_ai.services.outreach.send_pacing import next_bulk_interval_seconds


class SendPacingUnitTests(TestCase):
    @override_settings(
        OUTREACH_SEND_MIN_INTERVAL_SECONDS=1500,
        OUTREACH_SEND_MAX_INTERVAL_SECONDS=1500,
    )
    def test_interval_reads_settings(self):
        self.assertEqual(next_bulk_interval_seconds(), 1500)

    @override_settings(
        OUTREACH_SEND_MIN_INTERVAL_SECONDS=1200,
        OUTREACH_SEND_MAX_INTERVAL_SECONDS=1800,
    )
    def test_next_bulk_interval_in_range(self):
        for _ in range(20):
            wait = next_bulk_interval_seconds()
            self.assertGreaterEqual(wait, 1200)
            self.assertLessEqual(wait, 1800)

    @override_settings(
        OUTREACH_SEND_MIN_INTERVAL_SECONDS=0,
        OUTREACH_SEND_MAX_INTERVAL_SECONDS=0,
    )
    def test_zero_interval_disables_pacing(self):
        self.assertEqual(next_bulk_interval_seconds(), 0)
