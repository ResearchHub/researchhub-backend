from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from research_ai.models import OutreachMailboxConnection
from research_ai.services.outreach.email_sender import (
    ExpertFinderOutreachDisabledError,
)
from research_ai.services.outreach.gmail_sender import (
    GmailApiClient,
    GmailNeedsReauthError,
    GmailNotConnectedError,
    GmailSender,
    GmailSendError,
    build_raw_gmail_message,
    get_active_outreach_mailbox,
)
from user.tests.helpers import create_random_default_user


def _connect_gmail(user, email: str = "editor@gmail.com", **kwargs):
    defaults = {
        "email": email,
        "provider": OutreachMailboxConnection.Provider.GMAIL,
        "refresh_token": "refresh-token",
        "access_token": "access-token",
        "access_token_expires_at": timezone.now() + timedelta(hours=1),
        "scopes": ["https://www.googleapis.com/auth/gmail.send"],
        "status": OutreachMailboxConnection.Status.ACTIVE,
        "connected_at": timezone.now(),
    }
    defaults.update(kwargs)
    return OutreachMailboxConnection.objects.create(user=user, **defaults)


class GetActiveOutreachMailboxTests(TestCase):
    def test_raises_not_connected_when_missing(self):
        user = create_random_default_user("noconn")
        with self.assertRaises(GmailNotConnectedError):
            get_active_outreach_mailbox(user)

    def test_raises_needs_reauth(self):
        user = create_random_default_user("reauth")
        _connect_gmail(user, status=OutreachMailboxConnection.Status.NEEDS_REAUTH)
        with self.assertRaises(GmailNeedsReauthError):
            get_active_outreach_mailbox(user)

    def test_raises_not_connected_when_revoked(self):
        user = create_random_default_user("revoked")
        _connect_gmail(user, status=OutreachMailboxConnection.Status.REVOKED)
        with self.assertRaises(GmailNotConnectedError):
            get_active_outreach_mailbox(user)

    def test_returns_active_connection(self):
        user = create_random_default_user("active")
        conn = _connect_gmail(user)
        self.assertEqual(get_active_outreach_mailbox(user), conn)


class BuildRawGmailMessageTests(TestCase):
    def test_builds_decodable_mime_with_headers(self):
        import base64
        from email import message_from_bytes

        raw = build_raw_gmail_message(
            from_email="me@gmail.com",
            to_email="expert@edu",
            subject="Hello",
            html_body="<p>Body</p>",
            reply_to=["reply@researchhub.foundation"],
            cc=["cc@example.com"],
        )
        msg = message_from_bytes(base64.urlsafe_b64decode(raw))
        self.assertEqual(msg["From"], "me@gmail.com")
        self.assertEqual(msg["To"], "expert@edu")
        self.assertEqual(msg["Subject"], "Hello")
        self.assertEqual(msg["Reply-To"], "reply@researchhub.foundation")
        self.assertEqual(msg["Cc"], "cc@example.com")


@override_settings(EXPERT_FINDER_OUTREACH_ENABLED=True)
class GmailSenderTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("sender")
        self.connection = _connect_gmail(self.user)
        self.mock_client = Mock(spec=GmailApiClient)
        self.sender = GmailSender(client=self.mock_client)

    def test_send_uses_connected_mailbox_and_returns_ids(self):
        # Arrange
        self.mock_client.send_message.return_value = {
            "id": "gmail-msg-1",
            "threadId": "thread-1",
        }

        # Act
        result = self.sender.send(
            user=self.user,
            to_email="expert@edu",
            subject="Subject",
            body="<p>Hello</p>",
            reply_to=["reply@example.com"],
        )

        # Assert
        self.assertEqual(result.message_id, "gmail-msg-1")
        self.assertEqual(result.thread_id, "thread-1")
        kwargs = self.mock_client.send_message.call_args.kwargs
        self.assertEqual(kwargs["access_token"], "access-token")
        import base64
        from email import message_from_bytes

        msg = message_from_bytes(base64.urlsafe_b64decode(kwargs["raw"]))
        self.assertEqual(msg["From"], "editor@gmail.com")
        html_part = next(
            part.get_payload(decode=True).decode("utf-8")
            for part in msg.walk()
            if part.get_content_type() == "text/html"
        )
        self.assertEqual(html_part, "<p>Hello</p>")
        self.assertNotIn("/emails/t/", html_part)

    @patch(
        "research_ai.services.outreach.gmail_sender.get_google_oauth_credentials",
        return_value=("cid", "csecret"),
    )
    def test_send_refreshes_expired_access_token(self, _mock_creds):
        # Arrange
        self.connection.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        self.connection.save(update_fields=["access_token_expires_at"])
        self.mock_client.refresh_access_token.return_value = {
            "access_token": "new-access",
            "expires_in": 3600,
        }
        self.mock_client.send_message.return_value = {"id": "m1", "threadId": "t1"}

        # Act
        result = self.sender.send(
            user=self.user,
            to_email="expert@edu",
            subject="S",
            body="B",
        )

        # Assert
        self.assertEqual(result.message_id, "m1")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.access_token, "new-access")
        self.mock_client.send_message.assert_called_once()
        self.assertEqual(
            self.mock_client.send_message.call_args.kwargs["access_token"],
            "new-access",
        )

    @patch(
        "research_ai.services.outreach.gmail_sender.get_google_oauth_credentials",
        return_value=("cid", "csecret"),
    )
    def test_invalid_grant_marks_needs_reauth(self, _mock_creds):
        # Arrange
        self.connection.access_token_expires_at = timezone.now() - timedelta(minutes=1)
        self.connection.save(update_fields=["access_token_expires_at"])
        self.mock_client.refresh_access_token.side_effect = GmailNeedsReauthError()

        # Act / Assert
        with self.assertRaises(GmailNeedsReauthError):
            self.sender.send(
                user=self.user,
                to_email="expert@edu",
                subject="S",
                body="B",
            )

        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.status, OutreachMailboxConnection.Status.NEEDS_REAUTH
        )

    def test_send_401_marks_needs_reauth(self):
        self.mock_client.send_message.side_effect = GmailNeedsReauthError()
        with self.assertRaises(GmailNeedsReauthError):
            self.sender.send(
                user=self.user,
                to_email="expert@edu",
                subject="S",
                body="B",
            )
        self.connection.refresh_from_db()
        self.assertEqual(
            self.connection.status, OutreachMailboxConnection.Status.NEEDS_REAUTH
        )

    def test_missing_message_id_raises(self):
        self.mock_client.send_message.return_value = {"threadId": "t"}
        with self.assertRaises(GmailSendError):
            self.sender.send(
                user=self.user,
                to_email="expert@edu",
                subject="S",
                body="B",
            )

    @override_settings(EXPERT_FINDER_OUTREACH_ENABLED=False)
    def test_send_raises_when_outreach_disabled(self):
        with self.assertRaises(ExpertFinderOutreachDisabledError):
            self.sender.send(
                user=self.user,
                to_email="expert@edu",
                subject="S",
                body="B",
            )
        self.mock_client.send_message.assert_not_called()


class GmailApiClientTests(TestCase):
    def test_refresh_invalid_grant_raises_needs_reauth(self):
        session = Mock()
        response = Mock()
        response.status_code = 400
        response.json.return_value = {"error": "invalid_grant"}
        session.post.return_value = response
        client = GmailApiClient(session=session)

        with self.assertRaises(GmailNeedsReauthError):
            client.refresh_access_token(
                refresh_token="r",
                client_id="c",
                client_secret="s",
            )

    def test_send_message_401_raises_needs_reauth(self):
        session = Mock()
        response = Mock()
        response.status_code = 401
        response.json.return_value = {"error": {"code": 401, "message": "Unauthorized"}}
        response.text = "Unauthorized"
        session.post.return_value = response
        client = GmailApiClient(session=session)

        with self.assertRaises(GmailNeedsReauthError):
            client.send_message(access_token="a", raw="raw")
