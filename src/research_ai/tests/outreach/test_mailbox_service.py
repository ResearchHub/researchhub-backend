from datetime import date
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase

from research_ai.models import (
    EmailTemplate,
    GeneratedEmail,
    OutreachCampaign,
    OutreachMailbox,
)
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    GMAIL_IMAP_HOST,
    GMAIL_IMAP_PORT,
    GMAIL_SMTP_HOST,
    GMAIL_SMTP_PORT,
    PROVIDER_CODE_CUSTOM_IMAP_SMTP,
    InstantlyAPIError,
    InstantlyNotFoundError,
)
from research_ai.services.outreach.mailbox_service import (
    OAUTH_DONE_KEY,
    OAUTH_PENDING_KEY,
    MailboxAlreadyConnectedError,
    MailboxError,
    MailboxOAuthSessionNotFoundError,
    MailboxOwnedByOtherEditorError,
    OutreachMailboxService,
)
from user.tests.helpers import create_random_authenticated_user


class OutreachMailboxEmailNormalizationTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("om_email_norm")
        self.other = create_random_authenticated_user("om_email_norm_other")

    def test_save_normalizes_email_and_reply_to(self):
        # Arrange / Act
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="  Editor.Outreach@Gmail.COM ",
            reply_to="  Replies@ResearchHub.COM ",
        )

        # Assert
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.email, "editor.outreach@gmail.com")
        self.assertEqual(mailbox.reply_to, "replies@researchhub.com")

    def test_lower_unique_rejects_case_variant_for_another_editor(self):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="shared@gmail.com",
        )

        # Act / Assert
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OutreachMailbox.objects.create(
                    editor=self.other,
                    email="Shared@Gmail.com",
                )


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
        self.assertIsNone(kwargs["reply_to"])
        self.assertEqual(kwargs["first_name"], self.editor.first_name)
        self.assertEqual(kwargs["last_name"], self.editor.last_name)
        self.client.get_account.assert_called_once_with(self.gmail)

        mailbox.refresh_from_db()
        self.assertEqual(mailbox.editor_id, self.editor.id)
        self.assertEqual(mailbox.email, self.gmail)
        self.assertEqual(mailbox.status, OutreachMailbox.Status.ACTIVE)
        self.assertEqual(mailbox.daily_limit, 30)
        self.assertEqual(mailbox.reply_to, "")
        field_names = {f.name for f in mailbox._meta.get_fields()}
        self.assertNotIn("app_password", field_names)
        self.assertNotIn("password", field_names)
        self.assertNotIn(self.app_password, mailbox.__dict__.values())

    def test_connect_sends_and_caches_reply_to(self):
        # Arrange
        self.client.create_gmail_account.return_value = {"email": self.gmail}
        self.client.get_account.return_value = {
            "email": self.gmail,
            "status": 1,
            "daily_limit": 30,
            "provider_code": PROVIDER_CODE_CUSTOM_IMAP_SMTP,
            "reply_to": "replies@researchhub.com",
        }

        # Act
        mailbox = self.service.connect_mailbox(
            self.editor,
            email=self.gmail,
            app_password=self.app_password,
            reply_to="Replies@ResearchHub.com",
        )

        # Assert
        kwargs = self.client.create_gmail_account.call_args.kwargs
        self.assertEqual(kwargs["reply_to"], "replies@researchhub.com")
        self.assertEqual(mailbox.reply_to, "replies@researchhub.com")

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

    def test_connect_rejects_case_variant_already_connected(self):
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
                email=self.gmail.upper(),
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
        self.client.get_account.side_effect = lambda email: {
            "email": email,
            "daily_limit": 30,
        }
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

    @patch(
        "research_ai.services.outreach.mailbox_service.timezone.localdate",
        return_value=date(2099, 1, 1),
    )
    def test_capacity_refreshes_daily_limit_from_instantly(self, _mock_localdate):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.get_account.side_effect = lambda email: {
            "email": email,
            "daily_limit": 75,
        }
        self.client.get_daily_account_analytics.return_value = [
            {"date": "2099-01-01", "email_account": "a@gmail.com", "sent": 10},
        ]

        # Act
        summary = self.service.get_capacity_summary(self.editor)

        # Assert
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.daily_limit, 75)
        self.assertEqual(summary["daily_limit_total"], 75)
        self.assertEqual(summary["remaining_today"], 65)

    def test_update_daily_limit_patches_instantly_and_campaigns(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        OutreachCampaign.objects.create(
            editor=self.editor,
            template=EmailTemplate.objects.create(
                created_by=self.editor,
                name="T",
                email_subject="S",
                email_body="B",
            ),
            external_campaign_id="camp-1",
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.client.update_account.return_value = {
            "email": "a@gmail.com",
            "daily_limit": 50,
        }

        # Act
        updated = self.service.update_daily_limit(mailbox.id, 50)

        # Assert
        self.client.update_account.assert_called_once_with(
            "a@gmail.com", daily_limit=50
        )
        self.client.update_campaign.assert_called_once_with(
            "camp-1",
            email_list=["a@gmail.com"],
            daily_limit=50,
        )
        self.assertEqual(updated.daily_limit, 50)
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.daily_limit, 50)

    def test_update_mailbox_reply_to_patches_instantly(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.update_account.return_value = {
            "email": "a@gmail.com",
            "reply_to": "replies@researchhub.com",
        }

        # Act
        updated = self.service.update_mailbox(
            self.editor,
            mailbox.id,
            reply_to="Replies@ResearchHub.com",
        )

        # Assert
        self.client.update_account.assert_called_once_with(
            "a@gmail.com", reply_to="replies@researchhub.com"
        )
        self.assertEqual(updated.reply_to, "replies@researchhub.com")
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.reply_to, "replies@researchhub.com")

    def test_update_mailbox_clears_reply_to_with_null(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
            reply_to="replies@researchhub.com",
        )
        self.client.update_account.return_value = {
            "email": "a@gmail.com",
            "reply_to": None,
        }

        # Act
        updated = self.service.update_mailbox(
            self.editor,
            mailbox.id,
            reply_to="",
        )

        # Assert
        self.client.update_account.assert_called_once_with("a@gmail.com", reply_to=None)
        self.assertEqual(updated.reply_to, "")
        mailbox.refresh_from_db()
        self.assertEqual(mailbox.reply_to, "")

    def test_update_mailbox_rejects_daily_limit_for_non_moderator(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.editor.moderator = False
        self.editor.save(update_fields=["moderator"])

        # Act / Assert
        with self.assertRaises(MailboxError):
            self.service.update_mailbox(self.editor, mailbox.id, daily_limit=50)
        self.client.update_account.assert_not_called()

    def test_update_mailbox_enables_warmup_for_moderator(self):
        # Arrange
        mod = create_random_authenticated_user("om_wu_mod", moderator=True)
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.enable_warmup.return_value = {"id": "job-1"}
        self.client.get_account.side_effect = None
        self.client.get_account.return_value = {
            "email": "a@gmail.com",
            "warmup_status": 1,
        }

        # Act
        updated = self.service.update_mailbox(mod, mailbox.id, warmup_enabled=True)

        # Assert
        self.client.enable_warmup.assert_called_once_with(["a@gmail.com"])
        self.client.disable_warmup.assert_not_called()
        self.client.update_account.assert_not_called()
        self.assertTrue(updated.warmup_enabled)

    def test_update_mailbox_disables_warmup_for_moderator(self):
        # Arrange
        mod = create_random_authenticated_user("om_wu_off", moderator=True)
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.client.disable_warmup.return_value = {"id": "job-2"}
        self.client.get_account.side_effect = None
        self.client.get_account.return_value = {
            "email": "a@gmail.com",
            "warmup_status": 0,
        }

        # Act
        updated = self.service.update_mailbox(mod, mailbox.id, warmup_enabled=False)

        # Assert
        self.client.disable_warmup.assert_called_once_with(["a@gmail.com"])
        self.assertFalse(updated.warmup_enabled)

    def test_update_mailbox_rejects_warmup_for_non_moderator(self):
        # Arrange
        mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="a@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.editor.moderator = False
        self.editor.save(update_fields=["moderator"])

        # Act / Assert
        with self.assertRaises(MailboxError):
            self.service.update_mailbox(self.editor, mailbox.id, warmup_enabled=True)
        self.client.enable_warmup.assert_not_called()

    def test_list_all_mailboxes_for_moderator_attaches_warmup(self):
        # Arrange
        other = create_random_authenticated_user("om_list_other")
        mine = OutreachMailbox.objects.create(
            editor=self.editor,
            email="mine@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        OutreachMailbox.objects.create(
            editor=other,
            email="other@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=40,
        )
        self.client.iter_accounts.return_value = iter(
            [
                {"email": "mine@gmail.com", "warmup_status": 1},
                {"email": "other@gmail.com", "warmup_status": 0},
            ]
        )

        # Act
        rows = self.service.list_all_mailboxes_for_moderator()

        # Assert
        self.assertEqual(len(rows), 2)
        by_email = {m.email: m for m in rows}
        self.assertEqual(by_email["mine@gmail.com"].id, mine.id)
        self.assertTrue(by_email["mine@gmail.com"].warmup_enabled)
        self.assertFalse(by_email["other@gmail.com"].warmup_enabled)
        self.assertEqual(by_email["other@gmail.com"].editor.email, other.email)
        self.assertEqual(by_email["mine@gmail.com"].total_sent, 0)
        self.assertEqual(by_email["other@gmail.com"].total_sent, 0)

    def test_list_all_mailboxes_for_moderator_attaches_total_sent(self):
        # Arrange
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="mine@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        for _ in range(3):
            GeneratedEmail.objects.create(
                created_by=self.editor,
                expert_email="expert@uni.edu",
                status=GeneratedEmail.Status.SENT,
                sender_account="mine@gmail.com",
            )
        GeneratedEmail.objects.create(
            created_by=self.editor,
            expert_email="queued@uni.edu",
            status=GeneratedEmail.Status.SENDING,
            sender_account="mine@gmail.com",
        )
        GeneratedEmail.objects.create(
            created_by=self.editor,
            expert_email="other@uni.edu",
            status=GeneratedEmail.Status.SENT,
            sender_account="someone-else@gmail.com",
        )
        self.client.iter_accounts.return_value = iter(
            [{"email": "mine@gmail.com", "warmup_status": 0}]
        )

        # Act
        rows = self.service.list_all_mailboxes_for_moderator()

        # Assert
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].total_sent, 3)


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
            reply_to="replies@researchhub.com",
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
        self.assertEqual(kwargs["json"]["reply_to"], "replies@researchhub.com")
        self.assertNotIn("provider_type", kwargs["json"])
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )

    def test_send_test_email_posts_expected_payload(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {"status": "success"}
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        client.send_test_email(
            from_email="sender@gmail.com",
            to_email="me@example.com",
            subject="Hello",
            html="<p>Hi</p>",
        )

        # Assert
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/emails/test"))
        self.assertEqual(
            kwargs["json"],
            {
                "eaccount": "sender@gmail.com",
                "to_address_email_list": "me@example.com",
                "subject": "Hello",
                "body": {"html": "<p>Hi</p>"},
            },
        )

    def test_init_google_oauth_posts_expected_path(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {
            "session_id": "sess-1",
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth?x=1",
            "expires_at": "2024-01-15T10:30:00.000Z",
        }
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        result = client.init_google_oauth()

        # Assert
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/oauth/google/init"))
        self.assertEqual(kwargs.get("json"), {})
        self.assertEqual(result["session_id"], "sess-1")
        self.assertIn("auth_url", result)

    def test_get_oauth_session_status_gets_encoded_path(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {"status": "pending"}
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        result = client.get_oauth_session_status("sess/with special")

        # Assert
        args, _ = session.request.call_args
        self.assertEqual(args[0], "GET")
        self.assertTrue(args[1].endswith("/oauth/session/status/sess%2Fwith%20special"))
        self.assertEqual(result["status"], "pending")

    def test_enable_warmup_posts_emails(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {"id": "job-1"}
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        client.enable_warmup(["a@gmail.com"])

        # Assert
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/accounts/warmup/enable"))
        self.assertEqual(kwargs["json"], {"emails": ["a@gmail.com"]})

    def test_disable_warmup_posts_emails(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.content = b"{}"
        response.json.return_value = {"id": "job-2"}
        session.request.return_value = response
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        client.disable_warmup(["a@gmail.com"])

        # Assert
        args, kwargs = session.request.call_args
        self.assertEqual(args[0], "POST")
        self.assertTrue(args[1].endswith("/accounts/warmup/disable"))
        self.assertEqual(kwargs["json"], {"emails": ["a@gmail.com"]})

    def test_iter_accounts_follows_pagination(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import InstantlyClient

        session = MagicMock()
        page1 = MagicMock()
        page1.status_code = 200
        page1.content = b"{}"
        page1.json.return_value = {
            "items": [{"email": "a@gmail.com", "warmup_status": 1}],
            "next_starting_after": "cursor-1",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.content = b"{}"
        page2.json.return_value = {
            "items": [{"email": "b@gmail.com", "warmup_status": 0}],
            "next_starting_after": None,
        }
        session.request.side_effect = [page1, page2]
        client = InstantlyClient(api_key="test-key", session=session)

        # Act
        emails = [row["email"] for row in client.iter_accounts()]

        # Assert
        self.assertEqual(emails, ["a@gmail.com", "b@gmail.com"])
        self.assertEqual(session.request.call_count, 2)


class StartOAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.editor = create_random_authenticated_user("om_oauth_start")
        self.client = MagicMock()
        self.service = OutreachMailboxService(client=self.client)

    def test_start_oauth_google_binds_pending_session(self):
        # Arrange
        self.client.init_google_oauth.return_value = {
            "session_id": "sess-g",
            "auth_url": "https://accounts.google.com/auth",
            "expires_at": "2024-01-15T10:30:00.000Z",
        }

        # Act
        result = self.service.start_oauth(
            self.editor, reply_to="Replies@ResearchHub.com"
        )

        # Assert
        self.client.init_google_oauth.assert_called_once_with()
        self.assertEqual(result["session_id"], "sess-g")
        self.assertEqual(result["auth_url"], "https://accounts.google.com/auth")
        self.assertEqual(result["provider"], "google")
        pending = cache.get(OAUTH_PENDING_KEY.format(session_id="sess-g"))
        self.assertEqual(pending["editor_id"], self.editor.id)
        self.assertEqual(pending["provider"], "google")
        self.assertEqual(pending["reply_to"], "replies@researchhub.com")


class PollOAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self.editor = create_random_authenticated_user("om_oauth_poll")
        self.client = MagicMock()
        self.service = OutreachMailboxService(client=self.client)
        self.session_id = "sess-poll-1"
        self.workspace_email = "editor@company.com"
        cache.set(
            OAUTH_PENDING_KEY.format(session_id=self.session_id),
            {
                "editor_id": self.editor.id,
                "provider": "google",
                "reply_to": "",
            },
            timeout=600,
        )

    def test_poll_pending_returns_pending_without_mailbox(self):
        # Arrange
        self.client.get_oauth_session_status.return_value = {"status": "pending"}

        # Act
        result = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.assertEqual(result, {"status": "pending"})
        self.client.get_account.assert_not_called()
        self.assertIsNone(cache.get(OAUTH_DONE_KEY.format(session_id=self.session_id)))

    def test_poll_success_creates_mailbox_once_and_second_poll_uses_cache(self):
        # Arrange
        self.client.get_oauth_session_status.return_value = {
            "status": "success",
            "email": self.workspace_email,
            "account_id": self.workspace_email,
        }
        self.client.get_account.return_value = {
            "email": self.workspace_email,
            "status": 1,
            "daily_limit": 40,
            "provider_code": 2,
        }

        # Act
        first = self.service.poll_oauth(self.editor, self.session_id)
        second = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.assertEqual(first["status"], "success")
        self.assertEqual(first["email"], self.workspace_email)
        mailbox = first["mailbox"]
        self.assertEqual(mailbox.email, self.workspace_email)
        self.assertEqual(mailbox.provider_code, 2)
        self.assertEqual(mailbox.daily_limit, 40)
        self.assertEqual(mailbox.status, OutreachMailbox.Status.ACTIVE)

        self.assertEqual(second["status"], "success")
        self.assertEqual(second["mailbox"].id, mailbox.id)
        self.client.get_oauth_session_status.assert_called_once_with(self.session_id)
        self.client.get_account.assert_called_once_with(self.workspace_email)
        self.assertIsNone(
            cache.get(OAUTH_PENDING_KEY.format(session_id=self.session_id))
        )
        self.assertIsNotNone(
            cache.get(OAUTH_DONE_KEY.format(session_id=self.session_id))
        )

    def test_poll_applies_cached_reply_to_after_success(self):
        # Arrange
        cache.set(
            OAUTH_PENDING_KEY.format(session_id=self.session_id),
            {
                "editor_id": self.editor.id,
                "provider": "google",
                "reply_to": "replies@researchhub.com",
            },
            timeout=600,
        )
        self.client.get_oauth_session_status.return_value = {
            "status": "success",
            "email": self.workspace_email,
        }
        self.client.get_account.return_value = {
            "email": self.workspace_email,
            "status": 1,
            "daily_limit": 30,
            "provider_code": 2,
        }
        self.client.update_account.return_value = {
            "email": self.workspace_email,
            "reply_to": "replies@researchhub.com",
        }

        # Act
        result = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.client.update_account.assert_called_once_with(
            self.workspace_email, reply_to="replies@researchhub.com"
        )
        self.assertEqual(result["mailbox"].reply_to, "replies@researchhub.com")

    def test_poll_reply_to_patch_failure_still_returns_success(self):
        # Arrange
        cache.set(
            OAUTH_PENDING_KEY.format(session_id=self.session_id),
            {
                "editor_id": self.editor.id,
                "provider": "google",
                "reply_to": "replies@researchhub.com",
            },
            timeout=600,
        )
        self.client.get_oauth_session_status.return_value = {
            "status": "success",
            "email": self.workspace_email,
        }
        self.client.get_account.return_value = {
            "email": self.workspace_email,
            "status": 1,
            "daily_limit": 30,
            "provider_code": 2,
        }
        self.client.update_account.side_effect = InstantlyAPIError(
            "reply_to patch failed", status_code=502
        )

        # Act
        result = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["email"], self.workspace_email)
        mailbox = result["mailbox"]
        self.assertIsNotNone(mailbox.id)
        self.assertEqual(mailbox.email, self.workspace_email)
        self.assertEqual(mailbox.reply_to, "")
        self.client.update_account.assert_called_once_with(
            self.workspace_email, reply_to="replies@researchhub.com"
        )
        self.assertTrue(
            OutreachMailbox.objects.filter(
                editor=self.editor, email=self.workspace_email
            ).exists()
        )
        done = cache.get(OAUTH_DONE_KEY.format(session_id=self.session_id))
        self.assertEqual(done["status"], "success")
        self.assertEqual(done["mailbox_id"], mailbox.id)

    def test_poll_editor_mismatch_raises_not_found(self):
        # Arrange
        other = create_random_authenticated_user("om_oauth_other")

        # Act / Assert
        with self.assertRaises(MailboxOAuthSessionNotFoundError):
            self.service.poll_oauth(other, self.session_id)
        self.client.get_oauth_session_status.assert_not_called()

    def test_poll_rejects_email_owned_by_other_editor(self):
        # Arrange
        other = create_random_authenticated_user("om_oauth_owner")
        OutreachMailbox.objects.create(
            editor=other,
            email=self.workspace_email,
            status=OutreachMailbox.Status.ACTIVE,
        )
        self.client.get_oauth_session_status.return_value = {
            "status": "success",
            "email": self.workspace_email,
        }

        # Act / Assert
        with self.assertRaises(MailboxOwnedByOtherEditorError):
            self.service.poll_oauth(self.editor, self.session_id)
        self.client.get_account.assert_not_called()
        done = cache.get(OAUTH_DONE_KEY.format(session_id=self.session_id))
        self.assertEqual(done["conflict"], "owned_by_other")

    def test_poll_instantly_404_returns_expired_and_caches(self):
        # Arrange
        self.client.get_oauth_session_status.side_effect = InstantlyNotFoundError(
            "gone", status_code=404
        )

        # Act
        first = self.service.poll_oauth(self.editor, self.session_id)
        second = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.assertEqual(first, {"status": "expired"})
        self.assertEqual(second, {"status": "expired"})
        self.client.get_oauth_session_status.assert_called_once()

    def test_poll_restores_soft_deleted_mailbox_for_same_editor(self):
        # Arrange
        previous = OutreachMailbox.objects.create(
            editor=self.editor,
            email=self.workspace_email,
            status=OutreachMailbox.Status.DISCONNECTED,
            provider_code=1,
        )
        previous.delete(soft=True)
        self.client.get_oauth_session_status.return_value = {
            "status": "success",
            "email": self.workspace_email,
        }
        self.client.get_account.return_value = {
            "email": self.workspace_email,
            "status": 1,
            "daily_limit": 30,
            "provider_code": 3,
        }

        # Act
        result = self.service.poll_oauth(self.editor, self.session_id)

        # Assert
        self.assertEqual(result["mailbox"].id, previous.id)
        self.assertFalse(result["mailbox"].is_removed)
        self.assertEqual(result["mailbox"].provider_code, 3)
