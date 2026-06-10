from rest_framework.test import APITestCase

from paper.related_models.paper_version import PaperVersion
from paper.tests.helpers import create_paper
from researchhub_document.helpers import create_post
from researchhub_document.related_models.constants.document_type import (
    DISCUSSION,
    PREREGISTRATION,
)
from researchhub_document.related_models.researchhub_unified_document_model import (
    ResearchhubUnifiedDocument,
)
from user.tests.helpers import create_random_authenticated_user


class ContentModerationEndpointTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("cme_mod", moderator=True)
        self.author = create_random_authenticated_user("cme_author")

    def _pending_post(self, document_type=DISCUSSION):
        post = create_post(created_by=self.author, document_type=document_type)
        unified_document = post.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return post

    def _pending_paper(self):
        paper = create_paper(uploaded_by=self.author)
        unified_document = paper.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return paper

    def test_moderator_can_approve_post(self):
        # Arrange
        post = self._pending_post()
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(f"/api/researchhubpost/{post.id}/approve/")

        # Assert
        self.assertEqual(response.status_code, 200)
        post.unified_document.refresh_from_db()
        self.assertEqual(
            post.unified_document.status, ResearchhubUnifiedDocument.APPROVED
        )

    def test_moderator_can_decline_post(self):
        # Arrange
        post = self._pending_post()
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(
            f"/api/researchhubpost/{post.id}/decline/",
            {"reason": "Spam", "reason_choice": "SPAM"},
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        post.unified_document.refresh_from_db()
        self.assertEqual(
            post.unified_document.status, ResearchhubUnifiedDocument.DECLINED
        )

    def test_non_moderator_cannot_approve_post(self):
        # Arrange
        post = self._pending_post()
        self.client.force_authenticate(self.author)

        # Act
        response = self.client.post(f"/api/researchhubpost/{post.id}/approve/")

        # Assert
        self.assertEqual(response.status_code, 403)

    def test_moderator_can_approve_paper(self):
        # Arrange
        paper = self._pending_paper()
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.post(f"/api/paper/{paper.id}/approve/")

        # Assert
        self.assertEqual(response.status_code, 200)
        paper.unified_document.refresh_from_db()
        self.assertEqual(
            response.data,
            {
                "id": paper.id,
                "status": ResearchhubUnifiedDocument.APPROVED,
                "reviewed_by": self.moderator.id,
                "reviewed_date": response.data["reviewed_date"],
            },
        )
        self.assertEqual(
            paper.unified_document.status, ResearchhubUnifiedDocument.APPROVED
        )

    def test_non_moderator_cannot_decline_paper(self):
        # Arrange
        paper = self._pending_paper()
        self.client.force_authenticate(self.author)

        # Act
        response = self.client.post(f"/api/paper/{paper.id}/decline/")

        # Assert
        self.assertEqual(response.status_code, 403)


class PendingModerationFeedTests(APITestCase):
    def setUp(self):
        self.moderator = create_random_authenticated_user("pmf_mod", moderator=True)
        self.author = create_random_authenticated_user("pmf_author")

    def _pending_post(self, document_type):
        post = create_post(created_by=self.author, document_type=document_type)
        unified_document = post.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return post

    def _pending_paper(self):
        paper = create_paper(uploaded_by=self.author)
        unified_document = paper.unified_document
        unified_document.status = ResearchhubUnifiedDocument.PENDING
        unified_document.save(update_fields=["status"])
        return paper

    def test_pending_proposals_feed_returns_pending(self):
        # Arrange
        post = self._pending_post(PREREGISTRATION)
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            "/api/feed/pending_moderation/?content_type=PREREGISTRATION"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(post.id, ids)

    def test_pending_journal_entries_feed_returns_pending_papers(self):
        # Arrange
        paper = self._pending_paper()
        PaperVersion.objects.create(
            paper=paper,
            version=1,
            journal=PaperVersion.RESEARCHHUB,
            publication_status=PaperVersion.PREPRINT,
        )
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get(
            "/api/feed/pending_moderation/?content_type=PAPER"
        )

        # Assert
        self.assertEqual(response.status_code, 200)
        ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(paper.id, ids)

    def test_pending_papers_feed_includes_non_journal_preprints(self):
        # Arrange: a gated preprint never reaches the RESEARCHHUB journal, so it
        # must still surface in the queue rather than get stuck invisible.
        paper = self._pending_paper()
        self.client.force_authenticate(self.moderator)

        # Act
        response = self.client.get("/api/feed/pending_moderation/?content_type=PAPER")

        # Assert
        self.assertEqual(response.status_code, 200)
        ids = [r["content_object"]["id"] for r in response.data["results"]]
        self.assertIn(paper.id, ids)

    def test_pending_feed_requires_moderator(self):
        # Arrange
        self.client.force_authenticate(self.author)

        # Act
        response = self.client.get(
            "/api/feed/pending_moderation/?content_type=PREREGISTRATION"
        )

        # Assert
        self.assertEqual(response.status_code, 403)
