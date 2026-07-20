from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone

from discussion.models import Flag
from researchhub_document.helpers import create_post
from researchhub_document.models import ResearchhubPost
from researchhub_document.related_models.constants.document_type import (
    PREREGISTRATION,
    REGISTERED_REPORT,
)
from researchhub_document.tasks import (
    assign_preregistration_dois,
)
from user.tests.helpers import create_random_default_user


class AssignPreregistrationDoisTests(TestCase):
    """Verify delayed DOI assignment for preregistrations."""

    def setUp(self) -> None:
        """Set up a user who owns DOI-eligible posts."""
        self.user = create_random_default_user("doi_test_user")

    def _create_post(
        self,
        document_type: str = PREREGISTRATION,
        days_old: int = 10,
        doi: str | None = None,
        is_removed: bool = False,
    ) -> ResearchhubPost:
        """Create a post with the requested DOI assignment state."""
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

    def _build_mock_doi(
        self, doi_value: str = "10.55277/test123", status_code: int = 200
    ) -> MagicMock:
        """Build a DOI registration client with the requested response."""
        mock = MagicMock()
        mock.doi = doi_value
        mock.register_doi_for_post.return_value = MagicMock(status_code=status_code)
        return mock

    @patch("researchhub_document.tasks.DOI")
    def test_assigns_dois_to_eligible_preregistrations(
        self, mock_doi_cls: MagicMock
    ) -> None:
        """Verify eligible preregistrations receive their delayed DOIs."""
        # Arrange
        preregistration_doi = self._build_mock_doi("10.55277/proposal")
        mock_doi_cls.return_value = preregistration_doi
        preregistration = self._create_post(days_old=10)

        # Act
        assign_preregistration_dois()

        # Assert
        preregistration.refresh_from_db()
        self.assertEqual(preregistration.doi, "10.55277/proposal")
        self.assertEqual(
            preregistration_doi.register_doi_for_post.call_args.args[2],
            preregistration,
        )

    @patch("researchhub_document.tasks.DOI")
    def test_skips_ineligible_and_non_preregistration_works(
        self, mock_doi_cls: MagicMock
    ) -> None:
        """Verify ineligible posts and unrelated document types are skipped."""
        # Arrange
        self._create_post(days_old=3)
        self._create_post(days_old=10, is_removed=True)
        self._create_post(document_type="DISCUSSION", days_old=10)
        self._create_post(document_type="REGISTERED_REPORT", days_old=10)
        self._create_post(document_type="GRANT", days_old=10)
        self._create_post(document_type="QUESTION", days_old=10)

        flagged = self._create_post(REGISTERED_REPORT, days_old=10)
        ct = ContentType.objects.get_for_model(flagged)
        Flag.objects.create(
            content_type=ct,
            object_id=flagged.id,
            created_by=create_random_default_user("flagger"),
            reason="spam",
        )

        # Act
        assign_preregistration_dois()

        # Assert
        mock_doi_cls.assert_not_called()

    @patch("researchhub_document.tasks.DOI")
    def test_continues_when_preregistration_doi_registration_fails(
        self, mock_doi_cls: MagicMock
    ) -> None:
        """Verify a failed registration does not block later preregistrations."""
        # Arrange
        preregistration = self._create_post(days_old=10)
        second_preregistration = self._create_post(days_old=14)

        failing_doi = self._build_mock_doi("10.55277/fail")
        failing_doi.register_doi_for_post.side_effect = RuntimeError("Network error")
        success_doi = self._build_mock_doi("10.55277/ok")
        mock_doi_cls.side_effect = [failing_doi, success_doi]

        # Act
        assign_preregistration_dois()

        # Assert
        preregistration.refresh_from_db()
        second_preregistration.refresh_from_db()
        self.assertIsNone(preregistration.doi)
        self.assertEqual(second_preregistration.doi, "10.55277/ok")
