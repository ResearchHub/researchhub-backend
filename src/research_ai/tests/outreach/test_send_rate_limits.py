"""Tests for Expert Finder outreach send rate limits."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import GeneratedEmail, OutreachMailboxConnection
from research_ai.services.outreach.send_rate_limits import (
    RATE_LIMIT_CODE,
    get_send_quota,
    split_for_quota,
)
from user.tests.helpers import create_random_authenticated_user


def _connect_gmail(user, email: str = "editor@gmail.com"):
    return OutreachMailboxConnection.objects.create(
        user=user,
        email=email,
        provider=OutreachMailboxConnection.Provider.GMAIL,
        refresh_token="refresh-token",
        access_token="access-token",
        access_token_expires_at=timezone.now() + timedelta(hours=1),
        scopes=["https://www.googleapis.com/auth/gmail.send"],
        status=OutreachMailboxConnection.Status.ACTIVE,
        connected_at=timezone.now(),
    )


def _make_draft(user, *, email: str = "expert@example.com") -> GeneratedEmail:
    return GeneratedEmail.objects.create(
        created_by=user,
        expert_name="Dr. Expert",
        expert_email=email,
        email_subject="Subject",
        email_body="Body",
        status=GeneratedEmail.Status.DRAFT,
    )


def _make_counted(user, *, status_value: str, age: timedelta | None = None):
    rec = GeneratedEmail.objects.create(
        created_by=user,
        expert_name="Prior",
        expert_email=f"prior-{GeneratedEmail.objects.count()}@example.com",
        email_subject="Subj",
        email_body="Body",
        status=status_value,
    )
    if age is not None:
        GeneratedEmail.objects.filter(id=rec.id).update(
            updated_date=timezone.now() - age
        )
        rec.refresh_from_db()
    return rec


class SendQuotaUnitTests(TestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("quota_user")

    @override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=100)
    def test_counts_sent_and_sending_today(self):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)
        _make_counted(
            self.user,
            status_value=GeneratedEmail.Status.SENT,
            age=timedelta(days=2),
        )
        _make_draft(self.user)

        # Act
        quota = get_send_quota(self.user)

        # Assert
        self.assertEqual(quota.used_day, 2)
        self.assertEqual(quota.used_hour, 2)
        self.assertEqual(quota.remaining_day, 98)
        self.assertEqual(quota.remaining_hour, 8)
        self.assertEqual(quota.remaining, 8)

    @override_settings(OUTREACH_SEND_HOURLY_CAP=3, OUTREACH_SEND_DAILY_CAP=40)
    def test_hourly_cap_is_tighter_than_daily(self):
        for _ in range(3):
            _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)

        quota = get_send_quota(self.user)
        self.assertEqual(quota.remaining_hour, 0)
        self.assertEqual(quota.remaining_day, 37)
        self.assertEqual(quota.remaining, 0)

    def test_split_for_quota_preserves_order(self):
        to_queue, deferred = split_for_quota([1, 2, 3, 4, 5], 2)
        self.assertEqual(to_queue, [1, 2])
        self.assertEqual(deferred, [3, 4, 5])

        empty, all_deferred = split_for_quota([9, 8], 0)
        self.assertEqual(empty, [])
        self.assertEqual(all_deferred, [9, 8])


@override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=100)
class SendEmailRateLimitViewTests(APITestCase):
    def setUp(self):
        self.user = create_random_authenticated_user("rate_send", moderator=True)
        _connect_gmail(self.user)
        self.url = "/api/research_ai/expert-finder/emails/send/"

    def _post(self, ids):
        self.client.force_authenticate(self.user)
        return self.client.post(
            self.url,
            {"generated_email_ids": ids, "reply_to": ["reply@example.com"]},
            format="json",
        )

    @patch("research_ai.views.email_views.send_queued_emails_task")
    @override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=2)
    def test_daily_cap_defers_extra_ids(self, mock_task):
        # Arrange — one prior send today leaves room for one more of three drafts
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        drafts = [_make_draft(self.user, email=f"e{i}@ex.com") for i in range(3)]

        # Act
        response = self._post([d.id for d in drafts])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(body["deferred"], [drafts[1].id, drafts[2].id])
        self.assertEqual(body["remaining_today"], 0)

        drafts[0].refresh_from_db()
        drafts[1].refresh_from_db()
        drafts[2].refresh_from_db()
        self.assertEqual(drafts[0].status, GeneratedEmail.Status.SENDING)
        self.assertEqual(drafts[1].status, GeneratedEmail.Status.DRAFT)
        self.assertEqual(drafts[2].status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_called_once()
        self.assertEqual(
            mock_task.delay.call_args.kwargs["generated_email_ids"],
            [drafts[0].id],
        )

    @patch("research_ai.views.email_views.send_queued_emails_task")
    @override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=1)
    def test_zero_remaining_returns_429(self, mock_task):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        draft = _make_draft(self.user)

        # Act
        response = self._post([draft.id])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        body = response.json()
        self.assertEqual(body["code"], RATE_LIMIT_CODE)
        self.assertEqual(body["remaining_today"], 0)
        self.assertEqual(body["deferred"], [draft.id])
        draft.refresh_from_db()
        self.assertEqual(draft.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task")
    @override_settings(OUTREACH_SEND_HOURLY_CAP=1, OUTREACH_SEND_DAILY_CAP=40)
    def test_hourly_cap_defers_extra_ids(self, mock_task):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)
        drafts = [_make_draft(self.user, email=f"h{i}@ex.com") for i in range(2)]

        # Act
        response = self._post([d.id for d in drafts])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["remaining_hour"], 0)
        self.assertEqual(response.json()["deferred"], [drafts[0].id, drafts[1].id])
        for d in drafts:
            d.refresh_from_db()
            self.assertEqual(d.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()
