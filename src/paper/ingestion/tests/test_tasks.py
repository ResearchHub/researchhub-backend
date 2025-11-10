from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.tasks import (
    enrich_papers_with_openalex,
    update_recent_papers_with_metrics,
)
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


class OpenAlexTasksTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("testUser1")

        self.paper_recent = Paper.objects.create(
            title="Recent Paper with OpenAlex Data",
            doi="10.1371/journal.pone.0001234",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=3),
        )

        self.paper_old = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old.paper",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=40),
        )

        self.paper_no_doi = Paper.objects.create(
            title="No DOI Paper",
            uploaded_by=self.user,
            created_date=timezone.now() - timedelta(days=2),
        )

        # Sample OpenAlex API response
        self.sample_openalex_response = {
            "raw_data": {
                "id": "https://openalex.org/W2741809807",
                "doi": "https://doi.org/10.1371/journal.pone.0001234",
                "title": "Recent Paper with OpenAlex Data",
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A5023888391",
                            "display_name": "John Doe",
                            "orcid": "https://orcid.org/0000-0001-2345-6789",
                        },
                        "author_position": "first",
                        "institutions": [],
                    }
                ],
                "concepts": [
                    {
                        "id": "https://openalex.org/C71924100",
                        "display_name": "Neuroscience",
                        "level": 1,
                    }
                ],
                "primary_location": {
                    "pdf_url": "https://example.com/paper.pdf",
                    "license": "cc-by",
                    "version": "publishedVersion",
                },
                "open_access": {
                    "is_oa": True,
                    "oa_status": "gold",
                },
            }
        }

    @patch("paper.ingestion.tasks.OpenAlexClient")
    @patch("paper.ingestion.tasks.OpenAlexMapper")
    def test_enrich_papers_with_openalex(self, mock_mapper_class, mock_client_class):
        """
        Test successful enrichment of papers with OpenAlex data.
        """
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_openalex_response
        mock_client_class.return_value = mock_client

        # Create a mock Paper instance with license data
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_url = "https://example.com/paper.pdf"
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = (
            "https://creativecommons.org/licenses/by/4.0/"
        )
        mock_mapped_paper.citations = 25

        mock_mapper = Mock()
        mock_mapper.map_to_paper.return_value = mock_mapped_paper
        mock_mapper.map_to_authors.return_value = []
        mock_mapper.map_to_institutions.return_value = []
        mock_mapper.map_to_authorships.return_value = []
        mock_mapper.map_to_hubs.return_value = []
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = enrich_papers_with_openalex(days=30)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 2)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["error_count"], 0)

        # Verify client was called with the recent paper's DOI
        self.assertTrue(
            any(
                call[0][0] == self.paper_recent.doi
                for call in mock_client.fetch_by_doi.call_args_list
            ),
            f"Expected fetch_by_doi to be called with {self.paper_recent.doi}",
        )

        # Verify paper was updated with license data
        self.paper_recent.refresh_from_db()
        self.assertEqual(self.paper_recent.pdf_license, "cc-by")
        self.assertEqual(self.paper_recent.pdf_url, "https://example.com/paper.pdf")

    @patch("paper.ingestion.tasks.OpenAlexClient")
    @patch("paper.ingestion.tasks.OpenAlexMapper")
    def test_enrich_papers_preserves_existing_license(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test that existing license data is preserved and not overwritten.
        """
        # Arrange
        self.paper_recent.pdf_license = "existing-license"
        self.paper_recent.pdf_url = "https://existing.com/paper.pdf"
        self.paper_recent.save()

        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_openalex_response
        mock_client_class.return_value = mock_client

        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_url = "https://new.com/paper.pdf"
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.citations = 30

        mock_mapper = Mock()
        mock_mapper.map_to_paper.return_value = mock_mapped_paper
        mock_mapper.map_to_authors.return_value = []
        mock_mapper.map_to_institutions.return_value = []
        mock_mapper.map_to_authorships.return_value = []
        mock_mapper.map_to_hubs.return_value = []
        mock_mapper_class.return_value = mock_mapper

        # Act
        enrich_papers_with_openalex(days=30)

        # Assert
        self.paper_recent.refresh_from_db()
        # Existing license data should be preserved
        self.assertEqual(self.paper_recent.pdf_license, "existing-license")
        self.assertEqual(self.paper_recent.pdf_url, "https://existing.com/paper.pdf")

    @patch("paper.ingestion.tasks.OpenAlexClient")
    @patch("paper.ingestion.tasks.OpenAlexMapper")
    def test_enrich_papers_openalex_not_found(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test handling when OpenAlex data is not found for a paper.
        """
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = None  # Not found
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = enrich_papers_with_openalex(days=30)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["success_count"], 0)
        self.assertGreaterEqual(result["not_found_count"], 1)
        self.assertEqual(result["error_count"], 0)

        # Verify mapper methods were not called
        mock_mapper.map_to_paper.assert_not_called()
        mock_mapper.map_to_authors.assert_not_called()

    def test_enrich_papers_no_papers_in_date_range(self):
        """
        Test when no papers exist in the specified date range.
        """
        # Arrange
        Paper.objects.all().delete()

        # Act
        result = enrich_papers_with_openalex(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["papers_processed"], 0)
        self.assertIn("No papers with DOIs found", result["message"])

    @patch("paper.ingestion.tasks.OpenAlexClient")
    @patch("paper.ingestion.tasks.OpenAlexMapper")
    def test_enrich_papers_handles_client_exception(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test handling when the OpenAlex client raises an exception.
        """
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.side_effect = Exception("API Error")
        mock_client_class.return_value = mock_client

        mock_mapper = Mock()
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = enrich_papers_with_openalex(days=30)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["success_count"], 0)
        # Errors should be counted
        self.assertGreater(result["error_count"], 0)

    @patch("paper.ingestion.tasks.OpenAlexClient")
    @patch("paper.ingestion.tasks.OpenAlexMapper")
    def test_enrich_papers_with_authors_and_institutions(
        self, mock_mapper_class, mock_client_class
    ):
        """
        Test that authors and institutions are processed during enrichment.
        """
        # Arrange
        from institution.models import Institution
        from user.related_models.author_model import Author

        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_openalex_response
        mock_client_class.return_value = mock_client

        # Create mock author instance
        mock_author = Author(
            first_name="John",
            last_name="Doe",
            openalex_ids=["https://openalex.org/A5023888391"],
            orcid_id="0000-0001-2345-6789",
        )

        # Create mock institution instance
        mock_institution = Institution(
            display_name="Test University",
            openalex_id="https://openalex.org/I123456789",
            ror_id="https://ror.org/12345",
            type="education",
            associated_institutions=[],
        )

        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_url = "https://example.com/paper.pdf"
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.citations = 15

        mock_mapper = Mock()
        mock_mapper.map_to_paper.return_value = mock_mapped_paper
        mock_mapper.map_to_authors.return_value = [mock_author]
        mock_mapper.map_to_institutions.return_value = [mock_institution]
        mock_mapper.map_to_authorships.return_value = []
        mock_mapper.map_to_hubs.return_value = []
        mock_mapper_class.return_value = mock_mapper

        # Act
        result = enrich_papers_with_openalex(days=30)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["success_count"], 1)

        # Verify mapper methods were called
        self.assertTrue(mock_mapper.map_to_authors.called)
        self.assertTrue(mock_mapper.map_to_institutions.called)
