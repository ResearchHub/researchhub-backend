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
