from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from paper.models import Paper, PaperVersion
from paper.related_models.paper_model import JOURNAL_PAPER_IDS
from paper.tests.helpers import add_to_journal, create_paper
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
        self.pending_paper = add_to_journal(
            create_paper(title="Pending paper", uploaded_by=self.uploader)
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


class PaperJournalOnlyRetrieveTests(TestCase):
    """Only the journal's papers have pages; every other paper is not found."""

    def setUp(self):
        self.client = APIClient()
        self.journal_paper = add_to_journal(create_paper(title="Journal paper"))
        self.listed_paper = Paper.objects.create(
            id=min(JOURNAL_PAPER_IDS),
            title="Listed paper",
            unified_document=ResearchhubUnifiedDocument.objects.create(
                document_type="PAPER"
            ),
        )
        self.other_paper = create_paper(title="Other paper")

    def _status(self, paper):
        return self.client.get(reverse("paper-detail", args=[paper.id])).status_code

    def test_journal_version_paper_is_retrievable(self):
        # Act & Assert
        self.assertEqual(self._status(self.journal_paper), status.HTTP_200_OK)

    def test_listed_journal_paper_is_retrievable(self):
        # Act & Assert
        self.assertEqual(self._status(self.listed_paper), status.HTTP_200_OK)

    def test_versionless_original_of_journal_paper_is_retrievable(self):
        # Arrange
        original = create_paper(title="Original without a version row")
        PaperVersion.objects.create(
            paper=create_paper(title="Journal version 2"),
            version=2,
            original_paper=original,
            journal=PaperVersion.RESEARCHHUB,
        )

        # Act & Assert
        self.assertEqual(self._status(original), status.HTTP_200_OK)

    def test_other_paper_is_not_found(self):
        # Arrange
        self.client.force_authenticate(create_random_authenticated_user("reader"))

        # Act & Assert
        self.assertEqual(self._status(self.other_paper), status.HTTP_404_NOT_FOUND)

    def test_moderator_can_retrieve_other_paper(self):
        # Arrange
        moderator = create_random_authenticated_user("journal_mod", moderator=True)
        self.client.force_authenticate(moderator)

        # Act & Assert
        self.assertEqual(self._status(self.other_paper), status.HTTP_200_OK)
