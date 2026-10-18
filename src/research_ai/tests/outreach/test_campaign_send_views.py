from unittest.mock import patch

from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import (
    EmailTemplate,
    Expert,
    ExpertSearch,
    GeneratedEmail,
    OutreachCampaign,
    OutreachMailbox,
    SearchExpert,
)
from research_ai.services.outreach.mailbox_service import InsufficientDailyCapacityError
from user.tests.helpers import create_random_authenticated_user


class OutreachCampaignSendViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_send_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join us at {{expert.affiliation}}.",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-api-1",
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
        )
        SearchExpert.objects.create(
            expert_search=self.search,
            expert=self.expert,
            position=0,
        )
        self.url = f"/api/research_ai/expert-finder/outreach-campaigns/{self.campaign.id}/send/"

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_send_returns_queued_emails(self, mock_service_cls):
        # Arrange
        row = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="jane@example.edu",
            email_subject=self.campaign.published_subject,
            email_body=self.campaign.published_body,
            status=GeneratedEmail.Status.SENDING,
        )
        service = mock_service_cls.return_value
        service.send_to_experts.return_value = [row]
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.search.id,
                "expert_ids": [self.expert.id],
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        body = response.json()
        self.assertEqual(body["queued"], 1)
        self.assertEqual(len(body["emails"]), 1)
        service.send_to_experts.assert_called_once_with(
            self.editor,
            self.campaign.id,
            expert_search_id=self.search.id,
            expert_ids=[self.expert.id],
        )

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_send_over_capacity_returns_429(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.send_to_experts.side_effect = InsufficientDailyCapacityError(
            remaining=0, requested=1
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {
                "expert_search_id": self.search.id,
                "expert_ids": [self.expert.id],
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        body = response.json()
        self.assertEqual(body["remaining"], 0)
        self.assertEqual(body["requested"], 1)


class InstantlyWebhookViewTests(APITestCase):
    def setUp(self):
        self.url = "/api/research_ai/expert-finder/instantly/webhook/"
        self.secret = "test-webhook-secret"

    @patch("research_ai.views.template_views.InstantlyWebhookService")
    def test_webhook_requires_secret(self, mock_service_cls):
        # Arrange / Act
        with self.settings(INSTANTLY_WEBHOOK_SECRET=self.secret):
            response = self.client.post(
                self.url,
                {"event_type": "email_sent"},
                format="json",
            )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        mock_service_cls.assert_not_called()

    @patch("research_ai.views.template_views.InstantlyWebhookService")
    def test_webhook_accepts_bearer_secret_and_delegates(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.handle_event.return_value = "email_sent"

        # Act
        with self.settings(INSTANTLY_WEBHOOK_SECRET=self.secret):
            response = self.client.post(
                self.url,
                {
                    "event_type": "email_sent",
                    "campaign_id": "camp-1",
                    "lead_email": "jane@example.edu",
                },
                format="json",
                HTTP_AUTHORIZATION=f"Bearer {self.secret}",
            )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "ok", "disposition": "email_sent"})
        service.handle_event.assert_called_once()
