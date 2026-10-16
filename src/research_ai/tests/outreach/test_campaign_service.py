from unittest.mock import MagicMock

from django.test import TestCase

from research_ai.models import EmailTemplate, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.campaign_service import (
    CampaignNotFoundError,
    CampaignNotReadyError,
    CampaignTemplateNotFoundError,
    CampaignValidationError,
    OutreachCampaignService,
)
from research_ai.services.outreach.instantly_client import InstantlyNotFoundError
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
        campaign = self.service.publish_template(
            self.editor, self.template.id, name="Spring RFP blast"
        )

        # Assert
        self.client.create_campaign.assert_called_once()
        kwargs = self.client.create_campaign.call_args.kwargs
        self.assertEqual(kwargs["name"], "Spring RFP blast")
        self.assertEqual(kwargs["subject"], "Hello {{expert_name}}")
        self.assertIn("{{expert_name}}", kwargs["body"])
        self.assertIn("{{rfp_title}}", kwargs["body"])
        self.assertIn("{{expert_affiliation}}", kwargs["body"])
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], self.mailbox.daily_limit)
        self.client.activate_campaign.assert_called_once_with("camp-new")
        self.client.update_campaign.assert_not_called()

        campaign.refresh_from_db()
        self.assertEqual(campaign.editor_id, self.editor.id)
        self.assertEqual(campaign.template_id, self.template.id)
        self.assertEqual(campaign.name, "Spring RFP blast")
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
            name="Old name",
            external_campaign_id="camp-existing",
            published_subject="Old subject",
            published_body="Old body",
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.client.update_campaign.return_value = {"id": "camp-existing"}

        # Act
        campaign = self.service.publish_template(
            self.editor, self.template.id, name="Renamed campaign"
        )

        # Assert
        self.client.create_campaign.assert_not_called()
        self.client.update_campaign.assert_called_once()
        kwargs = self.client.update_campaign.call_args.kwargs
        self.assertEqual(self.client.update_campaign.call_args.args[0], "camp-existing")
        self.assertEqual(kwargs["name"], "Renamed campaign")
        self.assertEqual(kwargs["subject"], "Hello {{expert_name}}")
        self.assertIn("{{rfp_title}}", kwargs["body"])
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], self.mailbox.daily_limit)
        self.assertIn("campaign_schedule", kwargs)

        campaign.refresh_from_db()
        self.assertEqual(campaign.id, existing.id)
        self.assertEqual(campaign.name, "Renamed campaign")
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
            name="Same name",
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
        self.service.publish_template(self.editor, self.template.id, name="Same name")

        # Assert
        kwargs = self.client.update_campaign.call_args.kwargs
        self.assertEqual(kwargs["email_list"], [self.mailbox.email])
        self.assertEqual(kwargs["daily_limit"], self.mailbox.daily_limit)
        self.assertNotIn("name", kwargs)
        self.assertNotIn("subject", kwargs)
        self.assertNotIn("body", kwargs)
        self.assertNotIn("campaign_schedule", kwargs)

    def test_publish_uses_sum_of_mailbox_daily_limits(self):
        # Arrange
        self.mailbox.daily_limit = 40
        self.mailbox.save(update_fields=["daily_limit"])
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="second@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=25,
        )
        self.client.create_campaign.return_value = {"id": "camp-sum"}

        # Act
        self.service.publish_template(self.editor, self.template.id, name="Sum limits")

        # Assert
        kwargs = self.client.create_campaign.call_args.kwargs
        self.assertEqual(kwargs["daily_limit"], 65)
        self.assertEqual(
            set(kwargs["email_list"]), {self.mailbox.email, "second@gmail.com"}
        )

    def test_publish_recreates_when_instantly_returns_not_found(self):
        # Arrange
        OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Gone",
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
        campaign = self.service.publish_template(
            self.editor, self.template.id, name="Recreated"
        )

        # Assert
        self.client.create_campaign.assert_called_once()
        self.assertEqual(
            self.client.create_campaign.call_args.kwargs["name"], "Recreated"
        )
        self.client.activate_campaign.assert_called_once_with("camp-recreated")
        campaign.refresh_from_db()
        self.assertEqual(campaign.external_campaign_id, "camp-recreated")
        self.assertEqual(campaign.name, "Recreated")

    def test_publish_rejects_blank_name(self):
        # Arrange / Act / Assert
        with self.assertRaises(CampaignValidationError):
            self.service.publish_template(self.editor, self.template.id, name="   ")
        self.client.create_campaign.assert_not_called()

    def test_publish_rejects_missing_template(self):
        # Arrange / Act / Assert
        with self.assertRaises(CampaignTemplateNotFoundError):
            self.service.publish_template(self.editor, 999999, name="Missing template")
        self.client.create_campaign.assert_not_called()


class ActivateCampaignTests(TestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_act")
        self.client = MagicMock()
        self.service = OutreachCampaignService(client=self.client)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite Experts",
            email_subject="Hello",
            email_body="Body",
        )
        self.mailbox = OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
            daily_limit=30,
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Paused campaign",
            external_campaign_id="camp-paused",
            published_subject="Hello",
            published_body="Body",
            status=OutreachCampaign.Status.NO_ACTIVE_MAILBOXES,
        )

    def test_activate_resumes_instantly_campaign_and_sets_active(self):
        # Arrange
        self.client.update_campaign.return_value = {"id": "camp-paused"}
        self.client.activate_campaign.return_value = {"id": "camp-paused"}

        # Act
        result = self.service.activate_campaign(self.editor, self.campaign.id)

        # Assert
        self.client.update_campaign.assert_called_once_with(
            "camp-paused",
            email_list=[self.mailbox.email],
            daily_limit=30,
        )
        self.client.activate_campaign.assert_called_once_with("camp-paused")
        result.refresh_from_db()
        self.assertEqual(result.status, OutreachCampaign.Status.ACTIVE)

    def test_activate_requires_active_mailbox(self):
        # Arrange
        self.mailbox.status = OutreachMailbox.Status.DISCONNECTED
        self.mailbox.save(update_fields=["status"])

        # Act / Assert
        with self.assertRaises(CampaignNotReadyError):
            self.service.activate_campaign(self.editor, self.campaign.id)
        self.client.update_campaign.assert_not_called()
        self.client.activate_campaign.assert_not_called()

    def test_activate_requires_published_external_id(self):
        # Arrange
        self.campaign.external_campaign_id = ""
        self.campaign.save(update_fields=["external_campaign_id"])

        # Act / Assert
        with self.assertRaises(CampaignNotReadyError):
            self.service.activate_campaign(self.editor, self.campaign.id)

    def test_activate_not_found_for_other_editor(self):
        # Arrange
        other = create_random_authenticated_user("camp_act_other")

        # Act / Assert
        with self.assertRaises(CampaignNotFoundError):
            self.service.activate_campaign(other, self.campaign.id)
