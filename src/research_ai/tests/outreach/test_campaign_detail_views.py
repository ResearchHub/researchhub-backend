from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import EmailTemplate, OutreachCampaign
from research_ai.services.outreach.campaign_service import (
    CampaignNotEmptyError,
    CampaignNotFoundError,
)
from research_ai.services.outreach.instantly_client import InstantlyAPIError
from user.tests.helpers import create_random_authenticated_user


class OutreachCampaignDetailViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_det_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join us.",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Detail campaign",
            external_campaign_id="camp-det-1",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.url = (
            f"/api/research_ai/expert-finder/outreach-campaigns/{self.campaign.id}/"
        )

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_patch_updates_campaign(self, mock_service_cls):
        # Arrange
        self.campaign.name = "Renamed"
        self.campaign.published_subject = "Hi {{expert.name}}"
        mock_service_cls.return_value.update_campaign.return_value = self.campaign
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(
            self.url,
            {
                "name": "Renamed",
                "published_subject": "Hi {{expert.name}}",
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Renamed")
        self.assertNotIn("has_unpublished_changes", response.json())
        mock_service_cls.return_value.update_campaign.assert_called_once_with(
            self.editor,
            self.campaign.id,
            name="Renamed",
            published_subject="Hi {{expert.name}}",
        )

    def test_patch_requires_at_least_one_field(self):
        # Arrange
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(self.url, {}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_delete_returns_204(self, mock_service_cls):
        # Arrange
        mock_service_cls.return_value.delete_campaign.return_value = None
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_service_cls.return_value.delete_campaign.assert_called_once_with(
            self.editor, self.campaign.id
        )

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_delete_conflict_when_not_empty(self, mock_service_cls):
        # Arrange
        mock_service_cls.return_value.delete_campaign.side_effect = (
            CampaignNotEmptyError(
                "Cannot delete a campaign that has queued or sent emails."
            )
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn("Cannot delete", response.json()["detail"])

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_delete_not_found(self, mock_service_cls):
        # Arrange
        mock_service_cls.return_value.delete_campaign.side_effect = (
            CampaignNotFoundError("Outreach campaign not found.")
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.delete(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_patch_provider_error(self, mock_service_cls):
        # Arrange
        mock_service_cls.return_value.update_campaign.side_effect = InstantlyAPIError(
            "boom", status_code=502
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.patch(self.url, {"name": "X"}, format="json")

        # Assert
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
