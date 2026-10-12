from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import EmailTemplate, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.campaign_service import (
    CampaignTemplateNotFoundError,
    OutreachCampaignService,
)
from research_ai.services.outreach.instantly_client import (
    DEFAULT_ACCOUNT_DAILY_LIMIT,
    InstantlyNotFoundError,
)
from user.tests.helpers import create_random_authenticated_user


class PublishCampaignTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_pub")
        self.client = MagicMock()
        self.service = OutreachCampaignService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite Experts",
            email_subject="Hello {{expert.name}}",
            email_body=(
                "Dear {{expert.name}}, join {{rfp.title}} at {{expert.affiliation}}."
            ),
        )
        self.mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )

    def test_publish_creates_and_activates_instantly_campaign(self):
        # Arrange
        self.client.create_campaign.return_value = {"id": "camp-new"}

        # Act
        campaign = self.service.publish_template(self.editor, self.template.id)

        # Assert
        self.client.create_campaign.assert_called_once()
        kwargs = self.client.create_campaign.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Hello {{expert_name}}")
        self.assertIn("{{expert_name}}", kwargs["body"])
        self.assertIn("{{rfp_title}}", kwargs["body"])
        self.assertIn("{{expert_affiliation}}", kwargs["body"])
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], DEFAULT_ACCOUNT_DAILY_LIMIT)
        self.client.activate_campaign.assert_called_once_with("camp-new")
        self.client.update_campaign.assert_not_called()

        campaign.refresh_from_db()
        self.assertEqual(campaign.editor_id, self.editor.id)
        self.assertEqual(campaign.template_id, self.template.id)
        self.assertEqual(campaign.external_campaign_id, "camp-new")
        self.assertEqual(campaign.published_subject, self.template.email_subject)
        self.assertEqual(campaign.published_body, self.template.email_body)
        self.assertEqual(
            campaign.published_variable_keys,
            ["expert_affiliation", "expert_name", "rfp_title"],
        )
        self.assertEqual(campaign.status, OutreachCampaign.Status.ACTIVE)
        self.assertIsNotNone(campaign.published_at)

    def test_publish_updates_existing_when_snapshot_changed(self):
        # Arrange
        existing = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-existing",
            published_subject="Old subject",
            published_body="Old body",
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.client.update_campaign.return_value = {"id": "camp-existing"}

        # Act
        campaign = self.service.publish_template(self.editor, self.template.id)

        # Assert
        self.client.create_campaign.assert_not_called()
        self.client.update_campaign.assert_called_once()
        kwargs = self.client.update_campaign.call_args.kwargs
        self.assertEqual(self.client.update_campaign.call_args.args[0], "camp-existing")
        self.assertEqual(kwargs["subject"], "Hello {{expert_name}}")
        self.assertIn("{{rfp_title}}", kwargs["body"])
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], DEFAULT_ACCOUNT_DAILY_LIMIT)
        self.assertIn("campaign_schedule", kwargs)

        campaign.refresh_from_db()
        self.assertEqual(campaign.id, existing.id)
        self.assertEqual(campaign.published_subject, self.template.email_subject)
        self.assertEqual(
            campaign.published_variable_keys,
            ["expert_affiliation", "expert_name", "rfp_title"],
        )

    def test_publish_syncs_email_list_without_sequences_when_snapshot_unchanged(self):
        # Arrange
        OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-same",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=[
                "expert_affiliation",
                "expert_name",
                "rfp_title",
            ],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.client.update_campaign.return_value = {"id": "camp-same"}

        # Act
        self.service.publish_template(self.editor, self.template.id)

        # Assert
        kwargs = self.client.update_campaign.call_args.kwargs
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], DEFAULT_ACCOUNT_DAILY_LIMIT)
        self.assertNotIn("subject", kwargs)
        self.assertNotIn("body", kwargs)
        self.assertNotIn("campaign_schedule", kwargs)

    def test_publish_recreates_when_instantly_returns_not_found(self):
        # Arrange
        OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-gone",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.client.update_campaign.side_effect = InstantlyNotFoundError(
            "missing",
            status_code=404,
        )
        self.client.create_campaign.return_value = {"id": "camp-recreated"}

        # Act
        campaign = self.service.publish_template(self.editor, self.template.id)

        # Assert
        self.client.create_campaign.assert_called_once()
        self.client.activate_campaign.assert_called_once_with("camp-recreated")
        campaign.refresh_from_db()
        self.assertEqual(campaign.external_campaign_id, "camp-recreated")

    def test_publish_rejects_missing_template(self):
        # Arrange / Act / Assert
        with self.assertRaises(CampaignTemplateNotFoundError):
            self.service.publish_template(self.editor, 999999)
        self.client.create_campaign.assert_not_called()
