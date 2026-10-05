"""Tests for Expert Finder outreach send rate limits."""

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import GeneratedEmail, OutreachMailboxConnection
from research_ai.services.outreach.send_rate_limits import (
    BULK_IN_PROGRESS_CODE,
    RATE_LIMIT_CODE,
    get_daily_usage,
    get_send_quota,
)
from user.tests.helpers import create_random_authenticated_user

_PATCH_DAILY_CAP = (
    "research_ai.services.outreach.send_rate_limits.OUTREACH_SEND_DAILY_CAP"
)


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

    def test_counts_sent_and_sending_today(self):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)
        _make_counted(
            self.user,
            status_value=GeneratedEmail.Status.SENT,
            age=timedelta(days=2),
        )
        _make_counted(
            self.user,
            status_value=GeneratedEmail.Status.SENDING,
            age=timedelta(days=1),
        )
        _make_draft(self.user)

        # Act
        quota = get_send_quota(self.user)

        # Assert — yesterday's SENT is ignored; yesterday's SENDING still counts
        self.assertEqual(quota.used_day, 3)
        self.assertEqual(quota.remaining_day, 17)

    @patch(_PATCH_DAILY_CAP, 2)
    def test_sending_reserved_before_midnight_blocks_new_day_cap(self):
        # Arrange — paced bulk row still SENDING after 00:00
        _make_counted(
            self.user,
            status_value=GeneratedEmail.Status.SENDING,
            age=timedelta(days=1),
        )

        # Act
        quota = get_send_quota(self.user)
        usage = get_daily_usage(self.user)

        # Assert
        self.assertEqual(quota.used_day, 1)
        self.assertEqual(quota.remaining_day, 1)
        self.assertEqual(usage["sent_today"], 0)
        self.assertEqual(usage["queued_today"], 1)
        self.assertEqual(usage["remaining_today"], 1)

    def test_daily_usage_breakdown(self):
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)

        usage = get_daily_usage(self.user)
        self.assertEqual(usage["daily_cap"], 20)
        self.assertEqual(usage["sent_today"], 1)
        self.assertEqual(usage["queued_today"], 1)
        self.assertEqual(usage["remaining_today"], 18)
        self.assertIn("T", usage["resets_at"])


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
    @patch(_PATCH_DAILY_CAP, 2)
    def test_over_daily_cap_rejects_entire_request(self, mock_task):
        # Arrange — one prior send today leaves room for one; request three
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENT)
        drafts = [_make_draft(self.user, email=f"e{i}@ex.com") for i in range(3)]
        draft_ids = [d.id for d in drafts]

        # Act
        response = self._post(draft_ids)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        body = response.json()
        self.assertEqual(body["code"], RATE_LIMIT_CODE)
        self.assertEqual(body["requested"], 3)
        self.assertEqual(body["remaining_today"], 1)
        self.assertEqual(body["used_today"], 1)
        self.assertEqual(body["daily_cap"], 2)
        self.assertEqual(body["deferred"], draft_ids)
        for d in drafts:
            d.refresh_from_db()
            self.assertEqual(d.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task")
    @patch(_PATCH_DAILY_CAP, 1)
    def test_zero_remaining_returns_429_with_detail(self, mock_task):
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
        self.assertEqual(body["used_today"], 1)
        self.assertEqual(body["daily_cap"], 1)
        self.assertEqual(body["requested"], 1)
        self.assertIn("only 0 remaining today", body["detail"].lower())
        self.assertEqual(body["deferred"], [draft.id])
        draft.refresh_from_db()
        self.assertEqual(draft.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task")
    @patch(_PATCH_DAILY_CAP, 1)
    def test_sending_from_yesterday_consumes_todays_cap(self, mock_task):
        # Arrange — reservation from before 00:00 still occupies the slot
        _make_counted(
            self.user,
            status_value=GeneratedEmail.Status.SENDING,
            age=timedelta(days=1),
        )
        draft = _make_draft(self.user)

        # Act
        response = self._post([draft.id])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], RATE_LIMIT_CODE)
        self.assertEqual(response.json()["used_today"], 1)
        self.assertEqual(response.json()["remaining_today"], 0)
        draft.refresh_from_db()
        self.assertEqual(draft.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task")
    def test_bulk_blocked_while_sending_exists(self, mock_task):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)
        drafts = [_make_draft(self.user, email=f"b{i}@ex.com") for i in range(2)]

        # Act
        response = self._post([d.id for d in drafts])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()["code"], BULK_IN_PROGRESS_CODE)
        for d in drafts:
            d.refresh_from_db()
            self.assertEqual(d.status, GeneratedEmail.Status.DRAFT)
        mock_task.delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task")
    def test_single_send_allowed_while_bulk_sending(self, mock_task):
        # Arrange
        _make_counted(self.user, status_value=GeneratedEmail.Status.SENDING)
        draft = _make_draft(self.user)

        # Act
        response = self._post([draft.id])

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        draft.refresh_from_db()
        self.assertEqual(draft.status, GeneratedEmail.Status.SENDING)
        kwargs = mock_task.delay.call_args.kwargs
        self.assertTrue(kwargs["immediate"])
        self.assertEqual(kwargs["generated_email_ids"], [draft.id])

    @patch("research_ai.views.email_views.send_queued_emails_task")
    def test_bulk_queues_without_immediate(self, mock_task):
        drafts = [_make_draft(self.user, email=f"m{i}@ex.com") for i in range(2)]

        response = self._post([d.id for d in drafts])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        kwargs = mock_task.delay.call_args.kwargs
        self.assertFalse(kwargs["immediate"])
        self.assertEqual(kwargs["generated_email_ids"], [drafts[0].id, drafts[1].id])
