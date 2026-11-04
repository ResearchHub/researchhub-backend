from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.tests.helpers import create_paper
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import (
    create_random_authenticated_user,
)


class PaperPendingVisibilityTests(TestCase):
    """Papers awaiting moderation are not publicly retrievable by direct link."""

    def setUp(self):
        self.client = APIClient()
        self.uploader = create_random_authenticated_user("paper_uploader")
        self.pending_paper = create_paper(
            title="Pending paper", uploaded_by=self.uploader
        )
        self.pending_paper.unified_document.status = ResearchhubUnifiedDocument.PENDING
        self.pending_paper.unified_document.save(update_fields=["status"])
        self.detail_url = reverse("paper-detail", args=[self.pending_paper.id])

    def test_anonymous_cannot_retrieve_pending_paper(self):
        self.client.force_authenticate(None)
        self.assertEqual(
            self.client.get(self.detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_outsider_cannot_retrieve_pending_paper(self):
        outsider = create_random_authenticated_user("paper_outsider")
        self.client.force_authenticate(outsider)
        self.assertEqual(
            self.client.get(self.detail_url).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_uploader_can_retrieve_pending_paper(self):
        self.client.force_authenticate(self.uploader)
        self.assertEqual(
            self.client.get(self.detail_url).status_code, status.HTTP_200_OK
        )

    def test_moderator_can_retrieve_pending_paper(self):
        moderator = create_random_authenticated_user("paper_mod", moderator=True)
        self.client.force_authenticate(moderator)
        self.assertEqual(
            self.client.get(self.detail_url).status_code, status.HTTP_200_OK
        )
