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


class OutreachCampaignCancelQueuedViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_cancel_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello",
            email_body="Body",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Cancel test",
            external_campaign_id="camp-cancel-1",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.url = (
            f"/api/research_ai/expert-finder/outreach-campaigns/"
            f"{self.campaign.id}/cancel-queued/"
        )

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_cancel_queued_returns_cancelled_and_skipped(self, mock_service_cls):
        # Arrange
        row = GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="jane@example.edu",
            status=GeneratedEmail.Status.CLOSED,
        )
        service = mock_service_cls.return_value
        service.cancel_queued_emails.return_value = {
            "cancelled": [row],
            "cancelled_ids": [row.id],
            "cancelled_count": 1,
            "skipped_ids": [99],
        }
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {"generated_email_ids": [row.id, 99]},
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["cancelled"], 1)
        self.assertEqual(body["cancelled_ids"], [row.id])
        self.assertEqual(body["skipped_ids"], [99])
        self.assertEqual(len(body["emails"]), 1)
        service.cancel_queued_emails.assert_called_once_with(
            self.editor,
            self.campaign.id,
            generated_email_ids=[row.id, 99],
        )


class OutreachCampaignPreviewViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_preview_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Body",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            name="Preview test",
            external_campaign_id="camp-preview-api",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.url = (
            f"/api/research_ai/expert-finder/outreach-campaigns/"
            f"{self.campaign.id}/preview/"
        )

    @patch("research_ai.views.template_views.OutreachCampaignService")
    def test_preview_returns_rendered_copy(self, mock_service_cls):
        # Arrange
        service = mock_service_cls.return_value
        service.preview_campaign.return_value = {
            "subject": "Hello Jane",
            "html": "Body",
            "to_email": "me@example.com",
            "from_email": "sender@gmail.com",
            "from_mailbox_id": 7,
            "expert_id": 42,
            "expert_email": "jane@example.edu",
            "expert_search_id": 9,
            "instantly": {"status": "success"},
        }
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.post(
            self.url,
            {
                "expert_email": "jane@example.edu",
                "to_email": "me@example.com",
                "expert_search_id": 9,
                "from_mailbox_id": 7,
            },
            format="json",
        )

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["subject"], "Hello Jane")
        self.assertEqual(body["html"], "Body")
        self.assertEqual(body["to_email"], "me@example.com")
        self.assertEqual(body["from_email"], "sender@gmail.com")
        self.assertEqual(body["from_mailbox_id"], 7)
        self.assertEqual(body["expert_id"], 42)
        self.assertEqual(body["expert_email"], "jane@example.edu")
        self.assertEqual(body["expert_search_id"], 9)
        self.assertNotIn("instantly", body)
        service.preview_campaign.assert_called_once_with(
            self.editor,
            self.campaign.id,
            expert_email="jane@example.edu",
            to_email="me@example.com",
            expert_search_id=9,
            from_mailbox_id=7,
        )


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
