from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.tasks import update_recent_papers_with_metrics
from paper.models import Paper
from user.tests.helpers import create_random_default_user


class AltmetricTasksTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("testUser1")

        self.paper_recent = Paper.objects.create(
            title="Recent Paper",
            doi="10.1038/news.2011.490",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=3),
        )

        self.paper_old = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old.paper",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=10),
        )

        self.paper_no_doi = Paper.objects.create(
            title="No DOI Paper",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=2),
        )

        # Sample Altmetric API response
        self.sample_altmetric_response = {
            "altmetric_id": 241939,
            "cited_by_fbwalls_count": 5,
            "cited_by_tweeters_count": 138,
            "cited_by_bluesky_count": 0,
            "score": 140.5,
            "last_updated": 1334237127,
        }

    @patch("paper.ingestion.tasks.AltmetricClient")
    @patch("paper.ingestion.tasks.AltmetricMapper")
    def test_update_recent_papers_with_metrics(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test updating recent papers with Altmetric metrics.
        """
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_altmetric_response
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = {
            "altmetric_id": 241939,
            "facebook_count": 5,
            "twitter_count": 138,
            "score": 140.5,
        }
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = update_recent_papers_with_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        # Should process at least the recent paper with DOI
        self.assertGreaterEqual(result["papers_processed"], 1)
        self.assertGreaterEqual(result["success_count"], 1)
        self.assertEqual(result["error_count"], 0)

        # Verify client was called with the recent paper's DOI at least once
        self.assertTrue(
            any(
                call[0][0] == self.paper_recent.doi
                for call in mock_client.fetch_by_doi.call_args_list
            ),
            f"Expected fetch_by_doi to be called with {self.paper_recent.doi}",
        )

        # Verify paper was updated
        self.paper_recent.refresh_from_db()
        self.assertIsNotNone(self.paper_recent.external_metadata)
        self.assertIn("metrics", self.paper_recent.external_metadata)
        self.assertEqual(
            self.paper_recent.external_metadata["metrics"]["altmetric_id"], 241939
        )

    @patch("paper.ingestion.tasks.AltmetricClient")
    @patch("paper.ingestion.tasks.AltmetricMapper")
    def test_preserves_existing_external_metadata(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test that existing external_metadata keys are preserved.
        """
        # Arrange
        self.paper_recent.external_metadata = {
            "some_other_key": "some_value",
            "another_key": {"nested": "data"},
        }
        self.paper_recent.save()

        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_altmetric_response
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = {
            "altmetric_id": 241939,
            "score": 140.5,
        }
        mock_mapper_class.return_value = mock_mapper

        # Act
        update_recent_papers_with_metrics(days=7)

        # Assert
        self.paper_recent.refresh_from_db()
        self.assertEqual(
            self.paper_recent.external_metadata["some_other_key"], "some_value"
        )
        self.assertEqual(
            self.paper_recent.external_metadata["another_key"]["nested"], "data"
        )
        # And new metrics are added
        self.assertIn("metrics", self.paper_recent.external_metadata)
        self.assertEqual(
            self.paper_recent.external_metadata["metrics"]["altmetric_id"], 241939
        )

    @patch("paper.ingestion.tasks.AltmetricClient")
    @patch("paper.ingestion.tasks.AltmetricMapper")
    def test_handles_null_external_metadata(self, mock_mapper_class, mock_client_class):
        """
        Test handling papers with null external_metadata.
        """
        # Arrange
        self.paper_recent.external_metadata = None
        self.paper_recent.save()

        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_altmetric_response
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = {"altmetric_id": 241939}
        mock_mapper_class.return_value = mock_mapper

        # Act
        update_recent_papers_with_metrics(days=7)

        # Assert
        self.paper_recent.refresh_from_db()
        self.assertIsNotNone(self.paper_recent.external_metadata)
        self.assertIn("metrics", self.paper_recent.external_metadata)

    @patch("paper.ingestion.tasks.AltmetricClient")
    @patch("paper.ingestion.tasks.AltmetricMapper")
    def test_handles_altmetric_not_found(self, mock_mapper_class, mock_client_class):
        """
        Test handling when Altmetric data is not found.
        """
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = None  # Not found
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = update_recent_papers_with_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["success_count"], 0)
        self.assertGreaterEqual(result["not_found_count"], 1)
        self.assertEqual(result["error_count"], 0)

        # Verify mapper was not called
        mock_mapper.map_metrics.assert_not_called()

    @patch("paper.ingestion.tasks.AltmetricClient")
    @patch("paper.ingestion.tasks.AltmetricMapper")
    def test_no_papers_in_date_range(self, mock_mapper_class, mock_client_class):
        """
        Test when no papers exist in the specified date range.
        """
        # Arrange
        Paper.objects.all().delete()

        # Act
        result = update_recent_papers_with_metrics(days=1)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 0)
