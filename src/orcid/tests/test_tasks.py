from unittest.mock import patch

from django.test import TestCase

from orcid.tasks import fetch_orcid_works_task


class FetchOrcidWorksTaskTests(TestCase):
    @patch("orcid.tasks.sync_orcid_papers")
    def test_task_returns_result_on_success(self, mock_sync):
        mock_sync.return_value = {"papers_processed": 2, "author_id": 123}
        result = fetch_orcid_works_task(123)
        self.assertEqual(result["papers_processed"], 2)
        mock_sync.assert_called_once_with(123)

    @patch("orcid.tasks.sync_orcid_papers")
    def test_task_raises_on_failure(self, mock_sync):
        mock_sync.side_effect = ValueError("No ORCID connected")
        with self.assertRaises(ValueError):
            fetch_orcid_works_task(123)

