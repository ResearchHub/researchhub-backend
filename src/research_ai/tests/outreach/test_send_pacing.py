"""Tests for Expert Finder Gmail send pacing helpers."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import GeneratedEmail
from research_ai.services.outreach.send_pacing import (
    get_last_successful_send_at,
    min_interval_seconds,
    seconds_until_next_send,
)
from user.tests.helpers import create_random_authenticated_user


class SendPacingUnitTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("pace_unit")

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=360)
    def test_min_interval_reads_settings(self):
        self.assertEqual(min_interval_seconds(), 360)

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=360)
    def test_no_prior_send_is_ready(self):
        # Arrange / Act / Assert
        self.assertIsNone(get_last_successful_send_at(self.user))
        self.assertEqual(seconds_until_next_send(self.user), 0)

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=360)
    def test_sending_rows_do_not_start_pacing_clock(self):
        # Arrange — queue reservation must not block the first real send
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="queued@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
        )

        # Act / Assert
        self.assertEqual(seconds_until_next_send(self.user), 0)

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=360)
    def test_recent_sent_requires_wait(self):
        # Arrange
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="sent@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENT,
        )
        GeneratedEmail.objects.filter(id=rec.id).update(
            updated_date=timezone.now() - timedelta(seconds=120)
        )

        # Act
        wait = seconds_until_next_send(self.user)

        # Assert — ~240s remaining of a 360s interval
        self.assertGreaterEqual(wait, 230)
        self.assertLessEqual(wait, 240)

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=360)
    def test_stale_sent_is_ready(self):
        # Arrange
        rec = GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="old@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENT,
        )
        GeneratedEmail.objects.filter(id=rec.id).update(
            updated_date=timezone.now() - timedelta(seconds=400)
        )

        # Act / Assert
        self.assertEqual(seconds_until_next_send(self.user), 0)

    @override_settings(OUTREACH_SEND_MIN_INTERVAL_SECONDS=0)
    def test_zero_interval_disables_pacing(self):
        GeneratedEmail.objects.create(
            created_by=self.user,
            expert_email="sent@example.com",
            email_subject="Subj",
            email_body="Body",
            status=GeneratedEmail.Status.SENT,
        )
        self.assertEqual(seconds_until_next_send(self.user), 0)
