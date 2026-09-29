from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from purchase.models import Grant
from research_ai.models import (
    Expert,
    ExpertSearch,
    GeneratedEmail,
    OutreachMailboxConnection,
    SearchExpert,
)
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import GRANT
from user.tests.helpers import create_random_authenticated_user


def _make_grant(*, created_by, contacts=None):
    post = create_post(created_by=created_by, document_type=GRANT)
    grant = Grant.objects.create(
        created_by=created_by,
        unified_document=post.unified_document,
        amount=Decimal("50000.00"),
        currency="USD",
        organization="National Science Foundation",
        short_title="AI Healthcare RFP",
        description="Research grant for AI applications in healthcare",
        status=Grant.OPEN,
        end_date=timezone.now() + timedelta(days=30),
    )
    if contacts:
        grant.contacts.set(contacts)
    return grant


def _connect_gmail(user, email: str):
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


class InviteRfpApplicantsViewTests(APITestCase):
    def setUp(self):
        self.creator = create_random_authenticated_user("creator", moderator=False)
        self.contact = create_random_authenticated_user("contact", moderator=False)
        self.other = create_random_authenticated_user("other", moderator=False)
        self.moderator = create_random_authenticated_user("mod", moderator=True)
        _connect_gmail(self.creator, "creator@gmail.com")
        _connect_gmail(self.contact, "contact@gmail.com")
        _connect_gmail(self.moderator, "mod@gmail.com")
        self.grant = _make_grant(created_by=self.creator, contacts=[self.contact])
        self.url = (
            f"/api/research_ai/expert-finder/rfp/{self.grant.id}/invite-applicants/"
        )

    def _post(self, body=None):
        return self.client.post(
            self.url, body or {"emails": ["a@example.com"]}, format="json"
        )

    def test_requires_authentication(self):
        self.assertEqual(self._post().status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_unrelated_user(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self._post().status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_404_for_missing_grant(self):
        self.client.force_authenticate(self.creator)
        url = "/api/research_ai/expert-finder/rfp/999999/invite-applicants/"
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_emails_payload_required(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.post(self.url, {}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_email_returns_400(self):
        self.client.force_authenticate(self.creator)
        resp = self.client.post(self.url, {"emails": ["nope"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_creator_can_invite_and_queues_send(self, mock_delay):
        self.client.force_authenticate(self.creator)
        resp = self._post(
            {"emails": ["jane@example.com", "JOHN@example.com", "jane@example.com"]}
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        data = resp.json()
        self.assertEqual(data["queued"], 2)
        self.assertEqual(data["skipped_existing"], [])
        self.assertEqual(len(data["generated_email_ids"]), 2)

        emails = GeneratedEmail.objects.order_by("id")
        self.assertEqual(emails.count(), 2)
        self.assertEqual(
            set(emails.values_list("expert_email", flat=True)),
            {"jane@example.com", "john@example.com"},
        )
        for ge in emails:
            self.assertEqual(ge.status, GeneratedEmail.Status.SENDING)
            self.assertIn("AI Healthcare RFP", ge.email_subject)
            self.assertEqual(ge.created_by, self.creator)
            self.assertIsNotNone(ge.expert_search_id)
            self.assertEqual(
                ge.expert_search.unified_document_id, self.grant.unified_document_id
            )

        self.assertEqual(Expert.objects.count(), 2)
        self.assertEqual(SearchExpert.objects.count(), 2)
        search = ExpertSearch.objects.get()
        self.assertEqual(search.created_by, self.creator)
        self.assertEqual(search.unified_document_id, self.grant.unified_document_id)

        mock_delay.assert_called_once()
        kwargs = mock_delay.call_args.kwargs
        self.assertEqual(kwargs["reply_to"], [self.creator.email])
        self.assertEqual(kwargs["sender_user_id"], self.creator.id)
        self.assertNotIn("from_email", kwargs)
        self.assertEqual(
            sorted(kwargs["generated_email_ids"]),
            sorted(data["generated_email_ids"]),
        )
        self.assertEqual(data["deferred"], [])
        self.assertIn("remaining_today", data)

    def test_invite_without_gmail_returns_409(self):
        user = create_random_authenticated_user("invite_nogmail", moderator=False)
        grant = _make_grant(created_by=user)
        url = f"/api/research_ai/expert-finder/rfp/{grant.id}/invite-applicants/"
        self.client.force_authenticate(user)
        resp = self.client.post(url, {"emails": ["a@example.com"]}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(resp.json().get("code"), "gmail_not_connected")
        self.assertEqual(GeneratedEmail.objects.count(), 0)

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_grant_contact_can_invite(self, mock_delay):
        self.client.force_authenticate(self.contact)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 1)
        mock_delay.assert_called_once()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_moderator_can_invite(self, mock_delay):
        self.client.force_authenticate(self.moderator)
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 1)
        mock_delay.assert_called_once()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_skips_already_invited_emails(self, mock_delay):
        self.client.force_authenticate(self.creator)
        first = self._post({"emails": ["dup@example.com"]})
        self.assertEqual(first.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(first.json()["queued"], 1)

        second = self._post({"emails": ["dup@example.com", "new@example.com"]})
        self.assertEqual(second.status_code, status.HTTP_202_ACCEPTED)
        body = second.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(body["skipped_existing"], ["dup@example.com"])
        self.assertEqual(GeneratedEmail.objects.count(), 2)

        # First call + second call each queue once (second skipped only the dup).
        self.assertEqual(mock_delay.call_count, 2)

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_no_send_when_all_skipped(self, mock_delay):
        self.client.force_authenticate(self.creator)
        self.assertEqual(self._post().status_code, status.HTTP_202_ACCEPTED)
        mock_delay.reset_mock()
        resp = self._post()
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(resp.json()["queued"], 0)
        mock_delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    def test_rejects_non_open_grant(self, mock_delay):
        for blocked_status in (
            Grant.PENDING,
            Grant.CLOSED,
            Grant.COMPLETED,
            Grant.DECLINED,
        ):
            with self.subTest(status=blocked_status):
                self.grant.status = blocked_status
                self.grant.save(update_fields=["status"])
                self.client.force_authenticate(self.creator)
                resp = self._post()
                self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(GeneratedEmail.objects.count(), 0)
                mock_delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    @override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=1)
    def test_invite_respects_daily_cap(self, mock_delay):
        from research_ai.services.outreach.send_rate_limits import RATE_LIMIT_CODE

        GeneratedEmail.objects.create(
            created_by=self.creator,
            expert_email="prior@example.com",
            email_subject="Prior",
            email_body="Body",
            status=GeneratedEmail.Status.SENT,
        )
        self.client.force_authenticate(self.creator)
        resp = self._post({"emails": ["a@example.com", "b@example.com"]})
        self.assertEqual(resp.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        body = resp.json()
        self.assertEqual(body["code"], RATE_LIMIT_CODE)
        self.assertEqual(len(body["deferred"]), 2)
        self.assertEqual(GeneratedEmail.objects.filter(status="draft").count(), 2)
        mock_delay.assert_not_called()

    @patch("research_ai.views.email_views.send_queued_emails_task.delay")
    @override_settings(OUTREACH_SEND_HOURLY_CAP=10, OUTREACH_SEND_DAILY_CAP=1)
    def test_invite_queues_partial_under_daily_cap(self, mock_delay):
        self.client.force_authenticate(self.creator)
        resp = self._post({"emails": ["a@example.com", "b@example.com"]})
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED)
        body = resp.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(len(body["deferred"]), 1)
        self.assertEqual(body["remaining_today"], 0)
        self.assertEqual(
            GeneratedEmail.objects.filter(status=GeneratedEmail.Status.SENDING).count(),
            1,
        )
        self.assertEqual(
            GeneratedEmail.objects.filter(status=GeneratedEmail.Status.DRAFT).count(),
            1,
        )
        mock_delay.assert_called_once()
        self.assertEqual(len(mock_delay.call_args.kwargs["generated_email_ids"]), 1)
