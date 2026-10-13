from datetime import date
from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import EmailTemplate, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    GMAIL_IMAP_HOST,
    GMAIL_IMAP_PORT,
    GMAIL_SMTP_HOST,
    GMAIL_SMTP_PORT,
    PROVIDER_CODE_CUSTOM_IMAP_SMTP,
)
from research_ai.services.outreach.mailbox_service import (
    InsufficientDailyCapacityError,
    MailboxAlreadyConnectedError,
    MailboxOwnedByOtherEditorError,
    OutreachMailboxService,
)
from user.tests.helpers import create_random_authenticated_user


class ConnectMailboxTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_connect")
        self.client = MagicMock()
        self.service = OutreachMailboxService(client=self.client)
        self.gmail = "editor.outreach@gmail.com"
        self.app_password = "abcd-efgh-ijkl-mnop"

    def test_connect_creates_instantly_account_with_imap_payload_and_saves_mailbox(
        self,
    ):
        # Arrange
        self.client.create_gmail_account.return_value = {"email": self.gmail}
        self.client.get_account.return_value = {
            "email": self.gmail,
            "status": 1,
            "daily_limit": 30,
            "provider_code": PROVIDER_CODE_CUSTOM_IMAP_SMTP,
        }

        # Act
        mailbox = self.service.connect_mailbox(
            self.editor,
            email=self.gmail.upper(),
            app_password=self.app_password,
        )

        # Assert
        self.client.create_gmail_account.assert_called_once()
        kwargs = self.client.create_gmail_account.call_args.kwargs
        self.assertEqual(kwargs["email"], self.gmail)
        self.assertEqual(kwargs["app_password"], self.app_password)
        self.assertEqual(kwargs["daily_limit"], DEFAULT_ACCOUNT_DAILY_LIMIT)
        self.assertTrue(kwargs["enable_slow_ramp"])
        self.assertEqual(kwargs["first_name"], self.editor.first_name)
        self.assertEqual(kwargs["last_name"], self.editor.last_name)
        self.client.get_account.assert_called_once_with(self.gmail)

        mailbox.refresh_from_db()
        self.assertEqual(mailbox.editor_id, self.editor.id)
        self.assertEqual(mailbox.email, self.gmail)
        self.assertEqual(mailbox.status, OutreachMailbox.Status.ACTIVE)
        self.assertEqual(mailbox.daily_limit, 30)
        field_names = {f.name for f in mailbox._meta.get_fields()}
        self.assertNotIn("app_password", field_names)
        self.assertNotIn("password", field_names)
        self.assertNotIn(self.app_password, mailbox.__dict__.values())

    def test_connect_rejects_address_owned_by_another_editor(self):
        # Arrange
        other = create_random_authenticated_user("om_other")
        OutreachMailbox.objects.create(
            editor=other,
            email=self.gmail,
            status=OutreachMailbox.Status.ACTIVE,
        )

        # Act / Assert
        with self.assertRaises(MailboxOwnedByOtherEditorError):
            self.service.connect_mailbox(
                self.editor,
                email=self.gmail,
                app_password=self.app_password,
            )
        self.client.create_gmail_account.assert_not_called()

    def test_connect_restores_soft_deleted_mailbox_for_same_editor(self):
        # Arrange
        previous = OutreachMailbox.objects.create(
            editor=self.editor,
            email=self.gmail,
            status=OutreachMailbox.Status.DISCONNECTED,
        )
        previous.delete(soft=True)
        self.assertTrue(OutreachMailbox.all_objects.get(id=previous.id).is_removed)
        self.client.create_gmail_account.return_value = {"email": self.gmail}
        self.client.get_account.return_value = {
            "email": self.gmail,
            "status": 1,
            "daily_limit": 30,
            "provider_code": 1,
        }

        # Act
        mailbox = self.service.connect_mailbox(
            self.editor,
            email=self.gmail,
            app_password=self.app_password,
        )

        # Assert
        self.assertEqual(mailbox.id, previous.id)
        self.assertFalse(mailbox.is_removed)
        self.assertEqual(mailbox.status, OutreachMailbox.Status.ACTIVE)
        self.assertEqual(OutreachMailbox.objects.filter(email=self.gmail).count(), 1)

    def test_connect_rejects_already_connected_for_same_editor(self):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email=self.gmail,
            status=OutreachMailbox.Status.ACTIVE,
        )

        # Act / Assert
        with self.assertRaises(MailboxAlreadyConnectedError):
            self.service.connect_mailbox(
                self.editor,
                email=self.gmail,
                app_password=self.app_password,
            )


class DetachMailboxTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_detach")
        self.client = MagicMock()
        self.service = OutreachMailboxService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello",
            email_body="Body",
        )

    def test_detach_last_mailbox_pauses_campaign_and_soft_deletes(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="only@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-1",
            status=OutreachCampaign.Status.ACTIVE,
        )

        # Act
        result = self.service.detach_mailbox(self.editor, mailbox.id)

        # Assert
        self.client.update_campaign.assert_called_once_with(
            "camp-1",
            email_list=[],
            daily_limit=0,
        )
        self.client.pause_campaign.assert_called_once_with("camp-1")
        self.client.delete_account.assert_called_once_with("only@gmail.com")

        campaign.refresh_from_db()
        self.assertEqual(campaign.status, OutreachCampaign.Status.NO_ACTIVE_MAILBOXES)

        result.refresh_from_db()
        self.assertTrue(result.is_removed)
        self.assertEqual(result.status, OutreachMailbox.Status.DISCONNECTED)
        self.assertFalse(OutreachMailbox.objects.filter(id=mailbox.id).exists())

    def test_detach_with_remaining_mailbox_updates_email_list_without_pause(self):
        # Arrange
        keep = OutreachMailbox.objects.create(
            editor=self.editor,
            email="keep@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        remove = OutreachMailbox.objects.create(
            editor=self.editor,
            email="remove@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-2",
            status=OutreachCampaign.Status.ACTIVE,
        )

        # Act
        self.service.detach_mailbox(self.editor, remove.id)

        # Assert
        self.client.update_campaign.assert_called_once_with(
            "camp-2",
            email_list=[keep.email],
            daily_limit=DEFAULT_ACCOUNT_DAILY_LIMIT,
        )
        self.client.pause_campaign.assert_not_called()
        self.client.delete_account.assert_called_once_with(remove.email)


class CapacityTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_cap")
        self.client = MagicMock()
        self.service = OutreachMailboxService(client=self.client)

    @patch(
        "research_ai.services.outreach.mailbox_service.timezone.localdate",
        return_value=date(2099, 1, 1),
    )
    def test_remaining_capacity_subtracts_sent_today(self, _mock_localdate):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="b@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.get_daily_account_analytics.return_value = [
            {"date": "2099-01-01", "email_account": "a@gmail.com", "sent": 10},
            {"date": "2099-01-01", "email_account": "b@gmail.com", "sent": 5},
        ]

        # Act
        remaining = self.service.get_remaining_daily_capacity(self.editor)

        # Assert
        self.assertEqual(remaining, 45)
        self.assertEqual(self.service.assert_within_daily_capacity(self.editor, 45), 45)

    def test_assert_within_daily_capacity_rejects_over_capacity(self):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.get_daily_account_analytics.return_value = [
            {"email_account": "a@gmail.com", "sent": 25},
        ]

        # Act / Assert
        with self.assertRaises(InsufficientDailyCapacityError) as ctx:
            self.service.assert_within_daily_capacity(self.editor, 10)
        self.assertEqual(ctx.exception.remaining, 5)
        self.assertEqual(ctx.exception.requested, 10)

    @patch(
        "research_ai.services.outreach.mailbox_service.timezone.localdate",
        return_value=date(2099, 1, 1),
    )
    def test_capacity_summary_includes_inactive_mailboxes_with_zero_remaining(
        self, _mock_localdate
    ):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="err@gmail.com",
            status=OutreachMailbox.Status.ERROR,
            daily_limit=30,
        )
        self.client.get_daily_account_analytics.return_value = [
            {"date": "2099-01-01", "email_account": "a@gmail.com", "sent": 10},
        ]

        # Act
        summary = self.service.get_capacity_summary(self.editor)

        # Assert
        self.assertEqual(summary["active_mailbox_count"], 1)
        self.assertEqual(summary["daily_limit_total"], 30)
        self.assertEqual(summary["sent_today"], 10)
        self.assertEqual(summary["remaining_today"], 20)
        by_email = {row["email"]: row for row in summary["mailboxes"]}
        self.assertEqual(by_email["a@gmail.com"]["remaining_today"], 20)
        self.assertEqual(by_email["err@gmail.com"]["sent_today"], 0)
        self.assertEqual(by_email["err@gmail.com"]["remaining_today"], 0)
        self.client.get_daily_account_analytics.assert_called_once()
        emails_arg = self.client.get_daily_account_analytics.call_args.args[0]
        self.assertEqual(emails_arg, ["a@gmail.com"])


class InstantlyClientGmailPayloadTests(TestCase):
    def test_create_gmail_account_posts_imap_smtp_fields(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {"email": "user@gmail.com", "status": 1}
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        client.create_gmail_account(
            email="user@gmail.com",
            first_name="Ada",
            last_name="Lovelace",
            app_password="secret-app-password",
        )

        # Assert
        _, kwargs = session.request.call_args
        self.assertEqual(
            kwargs["json"]["provider_code"], PROVIDER_CODE_CUSTOM_IMAP_SMTP
        )
        self.assertEqual(kwargs["json"]["imap_host"], GMAIL_IMAP_HOST)
        self.assertEqual(kwargs["json"]["imap_port"], GMAIL_IMAP_PORT)
        self.assertEqual(kwargs["json"]["smtp_host"], GMAIL_SMTP_HOST)
        self.assertEqual(kwargs["json"]["smtp_port"], GMAIL_SMTP_PORT)
        self.assertEqual(kwargs["json"]["imap_password"], "secret-app-password")
        self.assertEqual(kwargs["json"]["smtp_password"], "secret-app-password")
        self.assertNotIn("provider_type", kwargs["json"])
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )
