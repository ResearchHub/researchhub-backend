from unittest.mock import Mock

from django.test import TestCase

from orcid.tasks import sync_orcid_papers_task


class SyncOrcidPapersTaskTests(TestCase):

    def test_calls_service(self):
        # Arrange
        mock_service = Mock()
        mock_service.sync_papers.return_value = {"papers_processed": 5, "author_id": 1}

        # Act
        result = sync_orcid_papers_task(1, service=mock_service)

        # Assert
        mock_service.sync_papers.assert_called_once_with(1)
        self.assertEqual(result["papers_processed"], 5)

    def test_raises_on_error(self):
        # Arrange
        mock_service = Mock()
        mock_service.sync_papers.side_effect = ValueError("No ORCID")

        # Act & Assert
        with self.assertRaises(ValueError):
            sync_orcid_papers_task(1, service=mock_service)
