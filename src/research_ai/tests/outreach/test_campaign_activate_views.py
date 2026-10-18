from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import EmailTemplate, OutreachCampaign, OutreachMailbox
from research_ai.services.outreach.campaign_service import (
    CampaignNotFoundError,
    CampaignNotReadyError,
)
from user.tests.helpers import create_random_authenticated_user


class OutreachCampaignActivateViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_act_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello",
            email_body="Body",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Paused campaign",
            external_campaign_id="camp-act-1",
            published_subject="Hello",
            published_body="Body",
            status=OutreachCampaign.Status.NO_ACTIVE_MAILBOXES,
        )
        OutreachMailbox.objects.create(
            editor=self.editor,
            email="sender@gmail.com",
            status=OutreachMailbox.Status.ACTIVE,
        )
        self.url = (
            f"/api/research_ai/expert-finder/outreach-campaigns/"
            f"{self.campaign.id}/activate/"
        )

    def test_activate_requires_auth(self):
        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_activate_returns_campaign(self, mock_service_cls):
        # Arrange
        self.campaign.status = OutreachCampaign.Status.ACTIVE
        self.campaign.save(update_fields=["status"])
        service = mock_service_cls.return_value
        service.activate_campaign.return_value = self.campaign
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["id"], self.campaign.id)
        self.assertEqual(body["status"], OutreachCampaign.Status.ACTIVE)
        self.assertEqual(body["name"], "Paused campaign")
        service.activate_campaign.assert_called_once_with(self.editor, self.campaign.id)

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_activate_not_found(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.activate_campaign.side_effect = CampaignNotFoundError(
            "Outreach campaign not found."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_activate_requires_mailbox(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.activate_campaign.side_effect = CampaignNotReadyError(
            "Connect at least one active mailbox before restoring this campaign."
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("mailbox", response.json()["detail"].lower())
