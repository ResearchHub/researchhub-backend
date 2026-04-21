from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from discussion.models import Flag
from researchhub_document.helpers import create_post
from researchhub_document.tasks import assign_post_dois
from user.tests.helpers import create_random_default_user


class AssignPostDoisTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("doi_test_user")

    def _create_post(self, document_type="PREREGISTRATION", days_old=10, doi=None, is_removed=False):
        post = create_post(
            title="Test Post",
            created_by=self.user,
            document_type=document_type,
        )
        post.doi = doi
        post.created_date = timezone.now() - timedelta(days=days_old)
        post.save(update_fields=["doi", "created_date"])

        if is_removed:
            post.unified_document.is_removed = True
            post.unified_document.save(update_fields=["is_removed"])

        return post

    def _build_mock_doi(self, doi_value="10.55277/test123", status_code=200):
        mock = MagicMock()
        mock.doi = doi_value
        mock.register_doi_for_post.return_value = MagicMock(status_code=status_code)
        return mock

    @patch("researchhub_document.tasks.DOI")
    def test_assigns_doi_to_eligible_posts(self, mock_doi_cls):
        # Arrange
        mock_doi_cls.side_effect = [
            self._build_mock_doi("10.55277/doi1"),
            self._build_mock_doi("10.55277/doi2"),
        ]
        preregistration = self._create_post("PREREGISTRATION", days_old=10)
        discussion = self._create_post("DISCUSSION", days_old=10)

        # Act
        assign_post_dois()

        # Assert
        preregistration.refresh_from_db()
        discussion.refresh_from_db()
        self.assertEqual(preregistration.doi, "10.55277/doi1")
        self.assertEqual(discussion.doi, "10.55277/doi2")

    @patch("researchhub_document.tasks.DOI")
    def test_skips_ineligible_posts(self, mock_doi_cls):
        """Posts that are too young, already have a DOI, are removed,
        are flagged, or are non-notebook types should all be skipped."""
        # Arrange
        self._create_post(days_old=3)
        self._create_post(days_old=10, doi="10.55277/existing")
        self._create_post(days_old=10, is_removed=True)
        self._create_post(document_type="GRANT", days_old=10)
        self._create_post(document_type="QUESTION", days_old=10)

        flagged = self._create_post(days_old=10)
        ct = ContentType.objects.get_for_model(flagged)
        Flag.objects.create(
            content_type=ct,
            object_id=flagged.id,
            created_by=create_random_default_user("flagger"),
            reason="spam",
        )

        # Act
        assign_post_dois()

        # Assert
        mock_doi_cls.assert_not_called()

    @patch("researchhub_document.tasks.DOI")
    def test_handles_crossref_failure_and_continues(self, mock_doi_cls):
        # Arrange
        self._create_post(days_old=10)
        self._create_post(days_old=14)

        failing_doi = self._build_mock_doi("10.55277/fail")
        failing_doi.register_doi_for_post.side_effect = RuntimeError("Network error")
        success_doi = self._build_mock_doi("10.55277/ok")
        mock_doi_cls.side_effect = [failing_doi, success_doi]

        # Act
        assign_post_dois()

        # Assert
        from researchhub_document.models import ResearchhubPost

        posts = ResearchhubPost.objects.filter(document_type="PREREGISTRATION")
        assigned = posts.exclude(doi__isnull=True).count()
        unassigned = posts.filter(doi__isnull=True).count()
        self.assertEqual(assigned, 1)
        self.assertEqual(unassigned, 1)
