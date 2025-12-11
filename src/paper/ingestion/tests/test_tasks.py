from datetime import timedelta
from unittest.mock import Mock, patch

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.tasks import (
    enrich_paper_with_bluesky_metrics,
    enrich_paper_with_github_metrics,
    enrich_paper_with_x_metrics,
    enrich_papers_with_openalex,
    update_recent_papers_with_bluesky_metrics,
    update_recent_papers_with_github_metrics,
    update_recent_papers_with_x_metrics,
)
from paper.models import Paper
from user.tests.helpers import create_random_default_user


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


class GithubMetricsTasksTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("testUser1")
        self.paper_recent = Paper.objects.create(
            title="Recent Paper",
            doi="10.1038/news.2011.490",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=3),
        )
        self.paper_old = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old.paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=10),
        )
        self.paper_no_doi = Paper.objects.create(
            title="No DOI Paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=2),
        )
        self.sample_github_response = {
            "total_mentions": 15,
            "term": "10.1038/news.2011.490",
            "breakdown": {"issues": 10, "commits": 3, "repositories": 2},
        }

    @patch("paper.ingestion.tasks.enrich_paper_with_github_metrics.delay")
    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_update_recent_papers_with_github_metrics_dispatches_tasks(
        self, mock_create_client, mock_delay
    ):
        """
        Test that the dispatcher task creates individual tasks for each paper.
        """
        # Arrange
        mock_create_client.return_value = Mock()

        # Act
        result = update_recent_papers_with_github_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["papers_dispatched"], 1)
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertIn(self.paper_recent.id, dispatched_ids)

    @patch("paper.ingestion.tasks.enrich_paper_with_github_metrics.delay")
    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_update_recent_papers_with_github_metrics_excludes_old_papers(
        self, mock_create_client, mock_delay
    ):
        """
        Test that old papers are excluded from GitHub metrics updates.
        """
        # Arrange
        Paper.objects.filter(id=self.paper_old.id).update(
            created_date=timezone.now() - timedelta(days=10)
        )
        mock_create_client.return_value = Mock()

        # Act
        result = update_recent_papers_with_github_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertNotIn(self.paper_old.id, dispatched_ids)

    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_with_github_metrics(self, mock_create_client):
        """
        Test successful enrichment of a single paper with GitHub metrics.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_mentions.return_value = self.sample_github_response
        mock_create_client.return_value = mock_client

        # Act
        result = enrich_paper_with_github_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)
        self.assertIn("metrics", result)
        self.paper_recent.refresh_from_db()
        self.assertIn("github_mentions", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_with_github_metrics_not_found(self, mock_create_client):
        """
        Test enrichment when paper does not exist.
        """
        # Arrange
        non_existent_id = -999

        # Act
        result = enrich_paper_with_github_metrics(non_existent_id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], non_existent_id)
        self.assertEqual(result["reason"], "paper_not_found")

    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_with_github_metrics_no_doi(self, mock_create_client):
        """
        Test enrichment of paper without DOI.
        """
        # Arrange
        mock_create_client.return_value = Mock()

        # Act
        result = enrich_paper_with_github_metrics(self.paper_no_doi.id)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["paper_id"], self.paper_no_doi.id)
        self.assertEqual(result["reason"], "no_doi")

    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_with_github_metrics_no_github_mentions(
        self, mock_create_client
    ):
        """
        Test enrichment when no GitHub mentions are found.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_mentions.return_value = None
        mock_create_client.return_value = mock_client

        # Act
        result = enrich_paper_with_github_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)

    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_with_github_metrics_preserves_existing_metadata(
        self, mock_create_client
    ):
        """
        Test that existing external_metadata is preserved during enrichment.
        """
        # Arrange
        self.paper_recent.external_metadata = {
            "existing_key": "existing_value",
            "metrics": {"x_count": 50.0},
        }
        self.paper_recent.save()
        mock_client = Mock()
        mock_client.get_mentions.return_value = self.sample_github_response
        mock_create_client.return_value = mock_client

        # Act
        result = enrich_paper_with_github_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.paper_recent.refresh_from_db()
        self.assertEqual(
            self.paper_recent.external_metadata["existing_key"], "existing_value"
        )
        self.assertIn("github_mentions", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks.sentry")
    @patch("paper.ingestion.tasks.PaperMetricsEnrichmentService")
    @patch("paper.ingestion.tasks._create_github_metrics_client")
    def test_enrich_paper_handles_service_error_with_max_retries(
        self, mock_create_client, mock_service_class, mock_sentry
    ):
        """
        Test error handling when max retries are exceeded.
        """
        # Arrange
        from celery.exceptions import MaxRetriesExceededError

        mock_create_client.return_value = Mock()
        mock_service = Mock()
        mock_service.enrich_paper_with_github_mentions.side_effect = Exception(
            "Service error"
        )
        mock_service_class.return_value = mock_service

        # Act
        with patch.object(
            enrich_paper_with_github_metrics,
            "retry",
            side_effect=MaxRetriesExceededError(),
        ):
            result = enrich_paper_with_github_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertIn("reason", result)
        self.assertTrue(mock_sentry.log_error.called)


class BlueskyMetricsTasksTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("testUser1")
        self.paper_recent = Paper.objects.create(
            title="Recent Paper",
            doi="10.1038/news.2011.490",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=3),
        )
        self.paper_old = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old.paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=10),
        )
        self.paper_no_doi = Paper.objects.create(
            title="No DOI Paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=2),
        )
        self.sample_bluesky_response = {
            "post_count": 25,
            "term": "10.1038/news.2011.490",
            "posts": [
                {"uri": "at://did:plc:abc123/app.bsky.feed.post/xyz", "like_count": 10}
            ],
        }

    @patch("paper.ingestion.tasks.enrich_paper_with_bluesky_metrics.delay")
    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_update_recent_papers_with_bluesky_metrics_dispatches_tasks(
        self, mock_metrics_client_class, mock_delay
    ):
        """
        Test that the dispatcher task creates individual tasks for each paper.
        """
        # Arrange
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = update_recent_papers_with_bluesky_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["papers_dispatched"], 1)
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertIn(self.paper_recent.id, dispatched_ids)

    @patch("paper.ingestion.tasks.enrich_paper_with_bluesky_metrics.delay")
    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_update_recent_papers_with_bluesky_metrics_excludes_old_papers(
        self, mock_metrics_client_class, mock_delay
    ):
        """
        Test that old papers are excluded from Bluesky metrics updates.
        """
        # Arrange
        Paper.objects.filter(id=self.paper_old.id).update(
            paper_publish_date=timezone.now() - timedelta(days=10)
        )
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = update_recent_papers_with_bluesky_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertNotIn(self.paper_old.id, dispatched_ids)

    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_with_bluesky_metrics(self, mock_metrics_client_class):
        """
        Test successful enrichment of a single paper with Bluesky metrics.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_metrics.return_value = self.sample_bluesky_response
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_bluesky_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)
        self.assertIn("metrics", result)
        self.paper_recent.refresh_from_db()
        self.assertIn("bluesky", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_with_bluesky_metrics_not_found(
        self, mock_metrics_client_class
    ):
        """
        Test enrichment when paper does not exist.
        """
        # Arrange
        non_existent_id = -999

        # Act
        result = enrich_paper_with_bluesky_metrics(non_existent_id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], non_existent_id)
        self.assertEqual(result["reason"], "paper_not_found")

    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_with_bluesky_metrics_no_doi(self, mock_metrics_client_class):
        """
        Test enrichment of paper without DOI.
        """
        # Arrange
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = enrich_paper_with_bluesky_metrics(self.paper_no_doi.id)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["paper_id"], self.paper_no_doi.id)
        self.assertEqual(result["reason"], "no_doi")

    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_with_bluesky_metrics_no_bluesky_mentions(
        self, mock_metrics_client_class
    ):
        """
        Test enrichment when no Bluesky mentions are found.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_metrics.return_value = None
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_bluesky_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)

    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_with_bluesky_metrics_preserves_existing_metadata(
        self, mock_metrics_client_class
    ):
        """
        Test that existing external_metadata is preserved during enrichment.
        """
        # Arrange
        self.paper_recent.external_metadata = {
            "existing_key": "existing_value",
            "metrics": {"x_count": 50.0},
        }
        self.paper_recent.save()
        mock_client = Mock()
        mock_client.get_metrics.return_value = self.sample_bluesky_response
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_bluesky_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.paper_recent.refresh_from_db()
        self.assertEqual(
            self.paper_recent.external_metadata["existing_key"], "existing_value"
        )
        self.assertIn("bluesky", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks.sentry")
    @patch("paper.ingestion.tasks.PaperMetricsEnrichmentService")
    @patch("paper.ingestion.tasks.BlueskyMetricsClient")
    def test_enrich_paper_handles_service_error_with_max_retries(
        self, mock_metrics_client_class, mock_service_class, mock_sentry
    ):
        """
        Test error handling when max retries are exceeded.
        """
        # Arrange
        from celery.exceptions import MaxRetriesExceededError

        mock_metrics_client_class.return_value = Mock()
        mock_service = Mock()
        mock_service.enrich_paper_with_bluesky.side_effect = Exception("Service error")
        mock_service_class.return_value = mock_service

        # Act
        with patch.object(
            enrich_paper_with_bluesky_metrics,
            "retry",
            side_effect=MaxRetriesExceededError(),
        ):
            result = enrich_paper_with_bluesky_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertIn("reason", result)
        self.assertTrue(mock_sentry.log_error.called)


class XMetricsTasksTests(TestCase):
    def setUp(self):
        self.user = create_random_default_user("testUser1")
        self.paper_recent = Paper.objects.create(
            title="Recent Paper",
            doi="10.1038/news.2011.490",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=3),
        )
        self.paper_old = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old.paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=10),
        )
        self.paper_no_doi = Paper.objects.create(
            title="No DOI Paper",
            uploaded_by=self.user,
            paper_publish_date=timezone.now() - timedelta(days=2),
        )
        self.sample_x_response = {
            "post_count": 25,
            "total_likes": 500,
            "total_reposts": 100,
            "total_replies": 50,
            "total_quotes": 25,
            "total_impressions": 10000,
            "posts": [
                {
                    "id": "1234567890",
                    "text": "Great paper on DOI 10.1038/news.2011.490",
                    "author_id": "123456",
                    "like_count": 50,
                }
            ],
        }

    @patch("paper.ingestion.tasks.enrich_paper_with_x_metrics.delay")
    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_update_recent_papers_with_x_metrics_dispatches_tasks(
        self, mock_metrics_client_class, mock_delay
    ):
        """
        Test that the dispatcher task creates individual tasks for each paper.
        """
        # Arrange
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = update_recent_papers_with_x_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["papers_dispatched"], 1)
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertIn(self.paper_recent.id, dispatched_ids)

    @patch("paper.ingestion.tasks.enrich_paper_with_x_metrics.delay")
    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_update_recent_papers_with_x_metrics_excludes_old_papers(
        self, mock_metrics_client_class, mock_delay
    ):
        """
        Test that old papers are excluded from X metrics updates.
        """
        # Arrange
        Paper.objects.filter(id=self.paper_old.id).update(
            paper_publish_date=timezone.now() - timedelta(days=10)
        )
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = update_recent_papers_with_x_metrics(days=7)

        # Assert
        self.assertEqual(result["status"], "success")
        dispatched_ids = [call[0][0] for call in mock_delay.call_args_list]
        self.assertNotIn(self.paper_old.id, dispatched_ids)

    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_with_x_metrics(self, mock_metrics_client_class):
        """
        Test successful enrichment of a single paper with X metrics.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_metrics.return_value = self.sample_x_response
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_x_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)
        self.assertIn("metrics", result)
        self.paper_recent.refresh_from_db()
        self.assertIn("x", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_with_x_metrics_not_found(self, mock_metrics_client_class):
        """
        Test enrichment when paper does not exist.
        """
        # Arrange
        non_existent_id = -999

        # Act
        result = enrich_paper_with_x_metrics(non_existent_id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], non_existent_id)
        self.assertEqual(result["reason"], "paper_not_found")

    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_with_x_metrics_no_doi(self, mock_metrics_client_class):
        """
        Test enrichment of paper without DOI.
        """
        # Arrange
        mock_metrics_client_class.return_value = Mock()

        # Act
        result = enrich_paper_with_x_metrics(self.paper_no_doi.id)

        # Assert
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["paper_id"], self.paper_no_doi.id)
        self.assertEqual(result["reason"], "no_doi")

    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_with_x_metrics_no_x_posts(self, mock_metrics_client_class):
        """
        Test enrichment when no X posts are found.
        """
        # Arrange
        mock_client = Mock()
        mock_client.get_metrics.return_value = None
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_x_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertEqual(result["doi"], self.paper_recent.doi)

    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_with_x_metrics_preserves_existing_metadata(
        self, mock_metrics_client_class
    ):
        """
        Test that existing external_metadata is preserved during enrichment.
        """
        # Arrange
        self.paper_recent.external_metadata = {
            "existing_key": "existing_value",
            "metrics": {"github_mentions": 50.0},
        }
        self.paper_recent.save()
        mock_client = Mock()
        mock_client.get_metrics.return_value = self.sample_x_response
        mock_metrics_client_class.return_value = mock_client

        # Act
        result = enrich_paper_with_x_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "success")
        self.paper_recent.refresh_from_db()
        self.assertEqual(
            self.paper_recent.external_metadata["existing_key"], "existing_value"
        )
        self.assertIn("x", self.paper_recent.external_metadata["metrics"])

    @patch("paper.ingestion.tasks.sentry")
    @patch("paper.ingestion.tasks.PaperMetricsEnrichmentService")
    @patch("paper.ingestion.tasks.XMetricsClient")
    def test_enrich_paper_handles_service_error_with_max_retries(
        self, mock_metrics_client_class, mock_service_class, mock_sentry
    ):
        """
        Test error handling when max retries are exceeded.
        """
        # Arrange
        from celery.exceptions import MaxRetriesExceededError

        mock_metrics_client_class.return_value = Mock()
        mock_service = Mock()
        mock_service.enrich_paper_with_x.side_effect = Exception("Service error")
        mock_service_class.return_value = mock_service

        # Act
        with patch.object(
            enrich_paper_with_x_metrics,
            "retry",
            side_effect=MaxRetriesExceededError(),
        ):
            result = enrich_paper_with_x_metrics(self.paper_recent.id)

        # Assert
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["paper_id"], self.paper_recent.id)
        self.assertIn("reason", result)
        self.assertTrue(mock_sentry.log_error.called)
