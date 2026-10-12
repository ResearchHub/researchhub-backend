from unittest.mock import MagicMock, patch

from django.test import TestCase

from research_ai.models import (
    EmailTemplate,
    GeneratedEmail,
    OutreachCampaign,
    OutreachMailbox,
)
from research_ai.services.outreach.webhook_service import InstantlyWebhookService
from user.tests.helpers import create_random_authenticated_user


class InstantlyWebhookServiceTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("wh_editor")
        self.client = MagicMock()
        self.service = InstantlyWebhookService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hi",
            email_body="Body",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-wh-1",
            published_subject="Hi",
            published_body="Body",
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.email = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_name="Jane Smith",
            expert_email="jane@example.edu",
            email_subject="Hi",
            email_body="Body",
            status=GeneratedEmail.Status.SENDING,
            external_lead_id="lead-1",
        )
        self.mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )

    def test_email_sent_is_idempotent(self):
        # Arrange
        payload = {
            "event_type": "email_sent",
            "campaign_id": "camp-wh-1",
            "lead_email": "jane@example.edu",
            "email_account": "sender@gmail.com",
            "timestamp": "2099-01-01T12:00:00Z",
        }

        # Act
        with (
            patch(
                "research_ai.services.outreach.webhook_service.ExpertPersist"
            ) as persist,
            patch(
                "research_ai.services.outreach.webhook_service."
                "grant_invited_expert_access_for_send"
            ),
        ):
            first = self.service.handle_event(payload)
            self.email.refresh_from_db()
            sent_at = self.email.sent_at
            second = self.service.handle_event(payload)
            self.email.refresh_from_db()

        # Assert
        self.assertEqual(first, "email_sent")
        self.assertEqual(second, "email_sent_idempotent")
        self.assertEqual(self.email.status, GeneratedEmail.Status.SENT)
        self.assertEqual(self.email.sent_at, sent_at)
        self.assertEqual(self.email.sender_account, "sender@gmail.com")
        persist.mark_last_email_sent_at.assert_called_once()

    def test_reply_received_sets_replied_at_only_once(self):
        # Arrange
        first_ts = "2099-01-01T12:00:00Z"
        second_ts = "2099-01-02T12:00:00Z"
        base = {
            "event_type": "reply_received",
            "campaign_id": "camp-wh-1",
            "lead_email": "jane@example.edu",
            "reply_text": "Thanks!",
            "reply_html": "<p>Thanks!</p>",
        }

        # Act
        self.service.handle_event({**base, "timestamp": first_ts})
        self.email.refresh_from_db()
        first_replied_at = self.email.replied_at
        disposition = self.service.handle_event({**base, "timestamp": second_ts})
        self.email.refresh_from_db()

        # Assert
        self.assertIsNotNone(first_replied_at)
        self.assertEqual(disposition, "reply_received_idempotent")
        self.assertEqual(self.email.replied_at, first_replied_at)
        self.assertNotIn("Thanks!", self.email.email_body)

    def test_email_opened_sets_opened_at_only_once(self):
        # Arrange
        payload = {
            "event_type": "email_opened",
            "campaign_id": "camp-wh-1",
            "lead_email": "jane@example.edu",
            "timestamp": "2099-01-01T12:00:00Z",
        }

        # Act
        self.service.handle_event(payload)
        self.email.refresh_from_db()
        opened_at = self.email.opened_at
        open_count = self.email.open_count
        self.service.handle_event({**payload, "timestamp": "2099-01-02T12:00:00Z"})
        self.email.refresh_from_db()

        # Assert
        self.assertIsNotNone(opened_at)
        self.assertEqual(self.email.opened_at, opened_at)
        self.assertEqual(self.email.open_count, open_count + 1)

    def test_account_error_is_idempotent_and_drops_from_campaigns(self):
        # Arrange
        payload = {
            "event_type": "account_error",
            "email_account": "sender@gmail.com",
        }

        # Act
        first = self.service.handle_event(payload)
        self.mailbox.refresh_from_db()
        self.campaign.refresh_from_db()
        second = self.service.handle_event(payload)
        self.mailbox.refresh_from_db()

        # Assert
        self.assertEqual(first, "account_error")
        self.assertEqual(second, "account_error_idempotent")
        self.assertEqual(self.mailbox.status, OutreachMailbox.Status.ERROR)
        self.assertEqual(
            self.campaign.status, OutreachCampaign.Status.NO_ACTIVE_MAILBOXES
        )
        self.client.update_campaign.assert_called_once()
        self.client.pause_campaign.assert_called_once_with("camp-wh-1")

    def test_unknown_event_ignored(self):
        # Arrange / Act
        disposition = self.service.handle_event(
            {"event_type": "lead_interested", "campaign_id": "camp-wh-1"}
        )

        # Assert
        self.assertEqual(disposition, "ignored_unknown_event")
        self.email.refresh_from_db()
        self.assertEqual(self.email.status, GeneratedEmail.Status.SENDING)
        self.assertIsNone(self.email.sent_at)
