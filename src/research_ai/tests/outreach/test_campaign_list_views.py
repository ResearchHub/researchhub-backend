from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from research_ai.models import (
    EmailTemplate,
    GeneratedEmail,
    OutreachCampaign,
)
from user.tests.helpers import create_random_authenticated_user


class OutreachCampaignListViewTests(APITestCase):
    def setUp(self):
        self.editor = create_random_authenticated_user("camp_list_v", moderator=True)
        self.template = EmailTemplate.objects.create(
            created_by=self.editor,
            name="Invite",
            email_subject="Hello {{expert.name}}",
            email_body="Join us.",
        )
        self.campaign = OutreachCampaign.objects.create(
            editor=self.editor,
            template=self.template,
            external_campaign_id="camp-list-1",
            published_subject=self.template.email_subject,
            published_body=self.template.email_body,
            published_variable_keys=["expert_name"],
            status=OutreachCampaign.Status.ACTIVE,
        )
        self.url = "/api/research_ai/expert-finder/outreach-campaigns/"

    def test_list_includes_aggregate_counts(self):
        # Arrange
        GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="a@example.edu",
            status=GeneratedEmail.Status.SENDING,
        )
        GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="b@example.edu",
            status=GeneratedEmail.Status.SENT,
            sent_at=timezone.now(),
            opened_at=timezone.now(),
        )
        GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="c@example.edu",
            status=GeneratedEmail.Status.SENT,
            sent_at=timezone.now(),
            replied_at=timezone.now(),
        )
        GeneratedEmail.objects.create(
            created_by=self.editor,
            outreach_campaign=self.campaign,
            expert_email="d@example.edu",
            status=GeneratedEmail.Status.BOUNCED,
            bounced_at=timezone.now(),
        )
        self.client.force_authenticate(self.editor)

        # Act
        response = self.client.get(self.url)

        # Assert
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["total"], 1)
        campaign = body["campaigns"][0]
        self.assertEqual(campaign["id"], self.campaign.id)
        self.assertEqual(
            campaign["counts"],
            {
                "queued": 1,
                "sent": 2,
                "opened": 1,
                "replied": 1,
                "bounced": 1,
            },
        )
