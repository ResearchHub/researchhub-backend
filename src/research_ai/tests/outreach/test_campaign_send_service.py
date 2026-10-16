from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    OutreachCampaign,
    OutreachMailbox,
    SearchExpert,
)
from research_ai.services.outreach.campaign_service import (
    CampaignNotFoundError,
    CampaignValidationError,
    OutreachCampaignService,
)
from user.tests.helpers import create_random_authenticated_user


class SendCampaignLeadsTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_send")
        self.client = MagicMock()
        self.service = OutreachCampaignService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join us at {{expert.affiliation}}.",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-1",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_affiliation", "expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        self.search = ExpertSearch.objects.create(
            created_by=self.editor,
            name="Search",
            query="ML",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.COMPLETED,
        )
        self.expert = Expert.objects.create(
            email="jane@example.edu",
            first_name="Jane",
            last_name="Smith",
            affiliation="MIT",
            academic_title="Professor",
            expertise="ML",
        )
        SearchExpert.objects.create(
            expert_search=self.search,
            expert=self.expert,
            position=0,
        )

    def test_send_adds_leads_and_creates_queued_generated_emails(self):
        # Arrange
        self.client.add_leads.return_value = {
            "created_leads": [
                {"id": "lead-1", "email": "jane@example.edu", "index": 0},
            ]
        }

        # Act
        emails = self.service.send_to_experts(
            self.editor,
            self.campaign.id,
            expert_search_id=self.search.id,
            expert_ids=[self.expert.id],
        )

        # Assert
        self.client.add_leads.assert_called_once()
        kwargs = self.client.add_leads.call_args.kwargs
        self.assertEqual(kwargs["campaign_id"], "camp-1")
        self.assertTrue(kwargs["skip_if_in_workspace"])
        lead = kwargs["leads"][0]
        self.assertEqual(lead["email"], "jane@example.edu")
        self.assertEqual(lead["first_name"], "Jane")
        self.assertEqual(lead["last_name"], "Smith")
        self.assertEqual(lead["company_name"], "MIT")
        self.assertEqual(lead["custom_variables"]["expert_name"], "Jane Smith")
        self.assertEqual(lead["custom_variables"]["expert_affiliation"], "MIT")

        self.assertEqual(len(emails), 1)
        row = emails[0]
        self.assertEqual(row.status, GeneratedEmail.Status.SENDING)
        self.assertEqual(row.outreach_campaign_id, self.campaign.id)
        self.assertEqual(row.external_lead_id, "lead-1")
        self.assertEqual(row.expert_email, "jane@example.edu")
        self.assertEqual(row.email_subject, self.campaign.published_subject)

    def test_send_rejects_missing_published_variables(self):
        # Arrange
        self.campaign.published_variable_keys = [
            "expert_name",
            "expert_affiliation",
            "rfp_title",
        ]
        self.campaign.save(update_fields=["published_variable_keys"])

        # Act / Assert
        with self.assertRaises(CampaignValidationError) as ctx:
            self.service.send_to_experts(
                self.editor,
                self.campaign.id,
                expert_search_id=self.search.id,
                expert_ids=[self.expert.id],
            )
        self.assertIn("rfp_title", str(ctx.exception))
        self.client.add_leads.assert_not_called()

    def test_cancel_queued_deletes_instantly_leads_and_local_rows(self):
        # Arrange
        pending = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="jane@example.edu",
            status=GeneratedEmail.Status.SENDING,
            external_lead_id="lead-1",
        )
        already_sent = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="sent@example.edu",
            status=GeneratedEmail.Status.SENT,
            external_lead_id="lead-2",
        )
        pending_id = pending.id
        self.client.delete_leads.return_value = {"deleted": 1}

        # Act
        result = self.service.cancel_queued_emails(
            self.editor,
            self.campaign.id,
            generated_email_ids=[pending_id, already_sent.id],
        )

        # Assert
        self.client.delete_leads.assert_called_once_with(
            campaign_id="camp-1",
            lead_ids=["lead-1"],
        )
        self.assertEqual(result["cancelled_count"], 1)
        self.assertEqual(result["cancelled_ids"], [pending_id])
        self.assertEqual(result["skipped_ids"], [already_sent.id])
        self.assertFalse(GeneratedEmail.objects.filter(id=pending_id).exists())
        already_sent.refresh_from_db()
        self.assertEqual(already_sent.status, GeneratedEmail.Status.SENT)

    def test_cancel_queued_deletes_local_when_instantly_lead_missing(self):
        # Arrange
        from research_ai.services.outreach.instantly_client import (
            InstantlyNotFoundError,
        )

        pending = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="jane@example.edu",
            status=GeneratedEmail.Status.SENDING,
            external_lead_id="lead-gone",
        )
        pending_id = pending.id
        self.client.delete_leads.side_effect = InstantlyNotFoundError(
            "missing", status_code=404
        )

        # Act
        result = self.service.cancel_queued_emails(
            self.editor,
            self.campaign.id,
            generated_email_ids=[pending_id],
        )

        # Assert
        self.assertEqual(result["cancelled_count"], 1)
        self.assertFalse(GeneratedEmail.objects.filter(id=pending_id).exists())


class PreviewCampaignTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_preview")
        self.client = MagicMock()
        self.service = OutreachCampaignService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join us at {{expert.affiliation}}.",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-preview-1",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_affiliation", "expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        self.expert = Expert.objects.create(
            email="jane@example.edu",
            first_name="Jane",
            last_name="Smith",
            affiliation="MIT",
        )

    def test_preview_renders_from_real_expert_and_sends_test_email(self):
        # Arrange
        self.client.send_test_email.return_value = {"status": "success"}

        # Act
        result = self.service.preview_campaign(
            self.editor,
            self.campaign.id,
            expert_email="Jane@Example.edu",
            to_email="me@example.com",
        )

        # Assert
        self.client.send_test_email.assert_called_once_with(
            from_email="sender@gmail.com",
            to_email="me@example.com",
            subject="Hello Jane Smith",
            html="Join us at MIT.",
        )
        self.assertEqual(result["subject"], "Hello Jane Smith")
        self.assertEqual(result["html"], "Join us at MIT.")
        self.assertEqual(result["from_mailbox_id"], self.mailbox.id)
        self.assertEqual(result["from_email"], "sender@gmail.com")
        self.assertEqual(result["expert_id"], self.expert.id)
        self.assertEqual(result["expert_email"], "jane@example.edu")
        self.assertIsNone(result["expert_search_id"])
        self.assertEqual(GeneratedEmail.objects.count(), 0)

    def test_preview_uses_mailbox_id_and_search_membership(self):
        # Arrange
        other = OutreachMailbox.objects.create(
            editor=self.editor,
            email="other@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        search = ExpertSearch.objects.create(
            created_by=self.editor,
            name="Search",
            query="ML",
            input_type=ExpertSearch.InputType.CUSTOM_QUERY,
            status=ExpertSearch.Status.COMPLETED,
        )
        SearchExpert.objects.create(
            expert_search=search,
            expert=self.expert,
            position=0,
        )
        self.client.send_test_email.return_value = {"status": "success"}

        # Act
        result = self.service.preview_campaign(
            self.editor,
            self.campaign.id,
            expert_email="jane@example.edu",
            to_email="me@example.com",
            expert_search_id=search.id,
            from_mailbox_id=other.id,
        )

        # Assert
        self.client.send_test_email.assert_called_once_with(
            from_email="other@gmail.com",
            to_email="me@example.com",
            subject="Hello Jane Smith",
            html="Join us at MIT.",
        )
        self.assertEqual(result["from_mailbox_id"], other.id)
        self.assertEqual(result["expert_search_id"], search.id)

    def test_preview_rejects_unknown_expert_email(self):
        # Act / Assert
        with self.assertRaises(CampaignValidationError) as ctx:
            self.service.preview_campaign(
                self.editor,
                self.campaign.id,
                expert_email="missing@example.edu",
                to_email="me@example.com",
            )
        self.assertIn("No expert found", str(ctx.exception))
        self.client.send_test_email.assert_not_called()

    def test_preview_rejects_unknown_campaign(self):
        # Act / Assert
        with self.assertRaises(CampaignNotFoundError):
            self.service.preview_campaign(
                self.editor,
                999999,
                expert_email="jane@example.edu",
                to_email="me@example.com",
            )
