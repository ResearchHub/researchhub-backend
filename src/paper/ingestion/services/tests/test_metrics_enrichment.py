from datetime import timedelta
from unittest.mock import Mock

from django.test import TestCase
from django.utils import timezone

from paper.ingestion.services import PaperMetricsEnrichmentService
from paper.models import Paper


class PaperMetricsEnrichmentServiceTests(TestCase):
    def setUp(self):
        self.paper = Paper.objects.create(
            title="Paper with DOI",
            doi="10.1038/news.2011.490",
            created_date=timezone.now() - timedelta(days=3),
        )

        self.paper_without_doi = Paper.objects.create(
            title="Paper without DOI",
            created_date=timezone.now() - timedelta(days=2),
        )

        # Sample response
        self.sample_altmetric_response = {
            "altmetric_id": 241939,
            "cited_by_fbwalls_count": 5,
            "cited_by_tweeters_count": 138,
            "score": 140.5,
            "last_updated": 1334237127,
        }

        self.mapped_metrics = {
            "altmetric_id": 241939,
            "facebook_count": 5,
            "twitter_count": 138,
            "score": 140.5,
        }

        # Create mocks for client and mapper
        self.mock_client = Mock()
        self.mock_mapper = Mock()

    def test_get_recent_papers_with_dois(self):
        """Test querying recent papers with DOIs."""
        # Arrange
        service = PaperMetricsEnrichmentService(self.mock_client, self.mock_mapper)

        # Act
        papers = service.get_recent_papers_with_dois(days=7)

        # Assert
        self.assertIn(self.paper.id, papers)
        # Verify all returned values are integers (paper IDs)
        self.assertTrue(all(isinstance(pid, int) for pid in papers))

    def test_get_recent_papers_excludes_old_papers(self):
        """Test that old papers are excluded."""
        # Arrange
        service = PaperMetricsEnrichmentService(self.mock_client, self.mock_mapper)
        # Create old paper (will have auto_now_add set to now)
        old_paper = Paper.objects.create(
            title="Old Paper",
            doi="10.1234/old",
        )
        # Update created_date to 30 days ago (bypasses auto_now_add)
        old_date = timezone.now() - timedelta(days=30)
        Paper.objects.filter(id=old_paper.id).update(created_date=old_date)
        old_paper.refresh_from_db()

        # Act
        papers = service.get_recent_papers_with_dois(days=7)

        # Assert
        self.assertNotIn(
            old_paper.id,
            papers,
            f"Old paper (created {old_paper.created_date}) "
            f"should be excluded from papers from last 7 days",
        )

    def test_enrich_paper_with_altmetric_success(self):
        """Test successful enrichment of a paper with Altmetric data."""
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_altmetric_response

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = self.mapped_metrics

        service = PaperMetricsEnrichmentService(
            altmetric_client=mock_client,
            altmetric_mapper=mock_mapper,
        )

        # Act
        result = service.enrich_paper_with_altmetric(self.paper)

        # Assert
        self.assertEqual(result.status, "success")
        self.assertEqual(result.altmetric_score, 140.5)
        self.assertEqual(result.metrics, self.mapped_metrics)

        # Verify client and mapper were called
        mock_client.fetch_by_doi.assert_called_once_with(self.paper.doi)
        mock_mapper.map_metrics.assert_called_once_with(self.sample_altmetric_response)

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertIsNotNone(self.paper.external_metadata)
        self.assertIn("metrics", self.paper.external_metadata)
        self.assertEqual(self.paper.external_metadata["metrics"], self.mapped_metrics)

    def test_enrich_paper_preserves_existing_metadata(self):
        """Test that existing metadata is preserved."""
        # Arrange
        self.paper.external_metadata = {
            "existing_key": "existing_value",
            "nested": {"data": "preserved"},
        }
        self.paper.save()

        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = self.sample_altmetric_response

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = self.mapped_metrics

        service = PaperMetricsEnrichmentService(
            altmetric_client=mock_client,
            altmetric_mapper=mock_mapper,
        )

        # Act
        service.enrich_paper_with_altmetric(self.paper)

        # Assert
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.external_metadata["existing_key"], "existing_value")
        self.assertEqual(self.paper.external_metadata["nested"]["data"], "preserved")
        self.assertIn("metrics", self.paper.external_metadata)

    def test_enrich_paper_no_doi(self):
        """Test enrichment of paper without DOI."""
        # Arrange
        service = PaperMetricsEnrichmentService(self.mock_client, self.mock_mapper)

        # Act
        result = service.enrich_paper_with_altmetric(self.paper_without_doi)

        # Assert
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "no_doi")

    def test_enrich_paper_altmetric_not_found(self):
        """Test enrichment when Altmetric data is not found."""
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.return_value = None

        mock_mapper = Mock()

        service = PaperMetricsEnrichmentService(mock_client, mock_mapper)

        # Act
        result = service.enrich_paper_with_altmetric(self.paper)

        # Assert
        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_altmetric_data")

    def test_enrich_paper_with_arxiv_id_success(self):
        """
        Test successful enrichment using arXiv ID.
        """
        # Arrange
        arxiv_paper = Paper.objects.create(
            title="arXiv Paper",
            doi="10.48550/arXiv.2101.12345",
            external_source="arxiv",
            external_metadata={"external_id": "2101.12345"},
            created_date=timezone.now() - timedelta(days=1),
        )

        mock_client = Mock()
        mock_client.fetch_by_arxiv_id.return_value = self.sample_altmetric_response

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = self.mapped_metrics

        service = PaperMetricsEnrichmentService(
            altmetric_client=mock_client,
            altmetric_mapper=mock_mapper,
        )

        # Act
        result = service.enrich_paper_with_altmetric(arxiv_paper)

        # Assert
        self.assertEqual(result.status, "success")
        self.assertEqual(result.altmetric_score, 140.5)
        self.assertEqual(result.metrics, self.mapped_metrics)

        # Verify client was called with arXiv ID, not DOI
        mock_client.fetch_by_arxiv_id.assert_called_once_with("2101.12345")
        mock_client.fetch_by_doi.assert_not_called()
        mock_mapper.map_metrics.assert_called_once_with(self.sample_altmetric_response)

        # Verify paper was updated
        arxiv_paper.refresh_from_db()
        self.assertIsNotNone(arxiv_paper.external_metadata)
        self.assertIsInstance(arxiv_paper.external_metadata, dict)
        self.assertIn("metrics", arxiv_paper.external_metadata)
        self.assertEqual(arxiv_paper.external_metadata["metrics"], self.mapped_metrics)

    def test_enrich_paper_arxiv_missing_arxiv_id(self):
        """
        Test enrichment of arXiv paper without arXiv ID is skipped.
        """
        # Arrange
        arxiv_paper = Paper.objects.create(
            title="arXiv paper without ID",
            doi="10.48550/arXiv.2101.12345",
            external_source="arxiv",
            external_metadata={},  # No external_id
            created_date=timezone.now() - timedelta(days=1),
        )

        mock_client = Mock()
        mock_mapper = Mock()

        service = PaperMetricsEnrichmentService(mock_client, mock_mapper)

        # Act
        result = service.enrich_paper_with_altmetric(arxiv_paper)

        # Assert
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "no_arxiv_id")

        # Verify no API calls were made
        mock_client.fetch_by_arxiv_id.assert_not_called()
        mock_client.fetch_by_doi.assert_not_called()

    def test_enrich_paper_arxiv_null_metadata(self):
        """
        Test enrichment of arXiv paper with null external_metadata is skipped.
        """
        # Arrange
        arxiv_paper = Paper.objects.create(
            title="arXiv Paper with null metadata",
            doi="10.48550/arXiv.2101.12345",
            external_source="arxiv",
            external_metadata=None,
            created_date=timezone.now() - timedelta(days=1),
        )

        mock_client = Mock()
        mock_mapper = Mock()

        service = PaperMetricsEnrichmentService(mock_client, mock_mapper)

        # Act
        result = service.enrich_paper_with_altmetric(arxiv_paper)

        # Assert
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "no_arxiv_id")

        # Verify no API calls were made
        mock_client.fetch_by_arxiv_id.assert_not_called()
        mock_client.fetch_by_doi.assert_not_called()

    def test_enrich_papers_batch(self):
        """Test batch enrichment of multiple papers."""
        # Arrange
        paper2 = Paper.objects.create(
            title="Paper 2",
            doi="10.1234/paper2",
            created_date=timezone.now() - timedelta(days=1),
        )

        mock_client = Mock()
        mock_client.fetch_by_doi.side_effect = [
            self.sample_altmetric_response,  # First paper succeeds
            None,  # Second paper not found
        ]

        mock_mapper = Mock()
        mock_mapper.map_metrics.return_value = self.mapped_metrics

        service = PaperMetricsEnrichmentService(
            altmetric_client=mock_client,
            altmetric_mapper=mock_mapper,
        )

        paper_ids = [self.paper.id, paper2.id]

        # Act
        results = service.enrich_papers_batch(paper_ids)

        # Assert
        self.assertEqual(results.total, 2)
        self.assertEqual(results.success_count, 1)
        self.assertEqual(results.not_found_count, 1)
        self.assertEqual(results.error_count, 0)

    def test_enrich_papers_batch_handles_errors(self):
        """Test batch enrichment handles errors gracefully."""
        # Arrange
        mock_client = Mock()
        mock_client.fetch_by_doi.side_effect = Exception("D'oh!")

        mock_mapper = Mock()

        service = PaperMetricsEnrichmentService(mock_client, mock_mapper)

        paper_ids = [self.paper.id]

        # Act
        results = service.enrich_papers_batch(paper_ids)

        # Assert
        self.assertEqual(results.error_count, 1)
        self.assertEqual(results.success_count, 0)
        self.assertEqual(results.success_count, 0)
