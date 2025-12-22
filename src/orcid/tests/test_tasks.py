from unittest.mock import Mock, patch

from django.test import TestCase

from orcid.tasks import sync_orcid_papers_task


class SyncOrcidPapersTaskTests(TestCase):

    @patch("orcid.tasks.OrcidFetchService")
    def test_calls_service(self, mock_service_class):
        mock_service = Mock()
        mock_service.sync_papers.return_value = {"papers_processed": 5, "author_id": 1}
        mock_service_class.return_value = mock_service

        result = sync_orcid_papers_task(1)

        mock_service.sync_papers.assert_called_once_with(1)
        self.assertEqual(result["papers_processed"], 5)

    @patch("orcid.tasks.OrcidFetchService")
    def test_raises_on_error(self, mock_service_class):
        mock_service = Mock()
        mock_service.sync_papers.side_effect = ValueError("No ORCID")
        mock_service_class.return_value = mock_service

        with self.assertRaises(ValueError):
            sync_orcid_papers_task(1)

