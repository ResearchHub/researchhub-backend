"""
Tests for the paper ingestion service.
"""

from unittest.mock import Mock, patch

from django.test import TestCase

from paper.ingestion.service import IngestionSource, PaperIngestionService
from paper.models import Paper


class TestPaperIngestionService(TestCase):
    """Test cases for PaperIngestionService."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = PaperIngestionService()

    def test_get_mappers(self):
        """Test getting all mappers and verify caching."""
        from paper.ingestion.mappers import ArXivMapper, BioRxivMapper, ChemRxivMapper

        # Test getting each mapper type
        arxiv_mapper = self.service.get_mapper(IngestionSource.ARXIV)
        self.assertIsInstance(arxiv_mapper, ArXivMapper)

        biorxiv_mapper = self.service.get_mapper(IngestionSource.BIORXIV)
        self.assertIsInstance(biorxiv_mapper, BioRxivMapper)

        chemrxiv_mapper = self.service.get_mapper(IngestionSource.CHEMRXIV)
        self.assertIsInstance(chemrxiv_mapper, ChemRxivMapper)

        # Test that mappers are cached after first creation
        arxiv_mapper2 = self.service.get_mapper(IngestionSource.ARXIV)
        self.assertIs(arxiv_mapper, arxiv_mapper2)

    def test_get_mapper_invalid_source(self):
        """Test that invalid source raises ValueError."""
        with self.assertRaises(ValueError) as context:
            self.service.get_mapper("invalid_source")
        self.assertIn("Unsupported ingestion source", str(context.exception))

    def test_ingest_papers_empty_response(self):
        """Test ingesting empty response returns empty lists."""
        papers, failures = self.service.ingest_papers([], IngestionSource.ARXIV)
        self.assertEqual(papers, [])
        self.assertEqual(failures, [])

    @patch("paper.ingestion.service.PaperIngestionService.get_mapper")
    def test_ingest_papers_validation_failure(self, mock_get_mapper):
        """Test handling of validation failures."""
        mock_mapper = Mock()
        mock_mapper.validate.return_value = False
        mock_get_mapper.return_value = mock_mapper

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, validate=True, save_to_db=False
        )

        self.assertEqual(len(papers), 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error"], "Validation failed")
        self.assertEqual(failures[0]["id"], "test123")

    @patch("paper.ingestion.service.PaperIngestionService.get_mapper")
    def test_ingest_papers_mapping_success_no_save(self, mock_get_mapper):
        """Test successful mapping without saving to database."""
        mock_paper = Mock(spec=Paper)
        mock_paper.id = 1
        mock_paper.title = "Test Paper"

        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.return_value = mock_paper
        mock_get_mapper.return_value = mock_mapper

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, save_to_db=False
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        self.assertEqual(papers[0], mock_paper)

    @patch("paper.ingestion.service.PaperIngestionService._save_paper")
    @patch("paper.ingestion.service.PaperIngestionService.get_mapper")
    def test_ingest_papers_with_save(self, mock_get_mapper, mock_save_paper):
        """Test ingestion with database save."""
        mock_paper = Mock(spec=Paper)
        mock_paper.id = 1
        mock_paper.title = "Test Paper"
        mock_paper.doi = "10.1234/test"

        mock_saved_paper = Mock(spec=Paper)
        mock_saved_paper.id = 1
        mock_saved_paper.title = "Test Paper"
        mock_save_paper.return_value = mock_saved_paper

        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.return_value = mock_paper
        mock_get_mapper.return_value = mock_mapper

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, save_to_db=True, update_existing=False
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        mock_save_paper.assert_called_once_with(mock_paper, False)

    @patch("paper.ingestion.service.PaperIngestionService.get_mapper")
    def test_ingest_papers_mapping_exception(self, mock_get_mapper):
        """Test handling of exceptions during mapping."""
        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.side_effect = Exception("Mapping error")
        mock_get_mapper.return_value = mock_mapper

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, save_to_db=False
        )

        self.assertEqual(len(papers), 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error"], "Mapping error")
        self.assertEqual(failures[0]["id"], "test123")

    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_new(self, mock_filter):
        """Test saving a new paper."""
        mock_filter.return_value.first.return_value = None

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"
        mock_paper.id = None
        mock_paper.title = "New Paper"
        mock_paper.save = Mock()

        result = self.service._save_paper(mock_paper, update_existing=False)

        mock_paper.save.assert_called_once()
        self.assertEqual(result, mock_paper)

    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_existing_no_update(self, mock_filter):
        """Test handling existing paper without update."""
        existing_paper = Mock(spec=Paper)
        existing_paper.id = 1
        existing_paper.doi = "10.1234/test"
        mock_filter.return_value.first.return_value = existing_paper

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"
        mock_paper.save = Mock()

        result = self.service._save_paper(mock_paper, update_existing=False)

        mock_paper.save.assert_not_called()
        self.assertEqual(result, existing_paper)

    @patch("paper.ingestion.service.PaperIngestionService._update_paper")
    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_existing_with_update(self, mock_filter, mock_update):
        """Test updating an existing paper."""
        existing_paper = Mock(spec=Paper)
        existing_paper.id = 1
        existing_paper.doi = "10.1234/test"
        mock_filter.return_value.first.return_value = existing_paper

        updated_paper = Mock(spec=Paper)
        mock_update.return_value = updated_paper

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"

        result = self.service._save_paper(mock_paper, update_existing=True)

        mock_update.assert_called_once_with(existing_paper, mock_paper)
        self.assertEqual(result, updated_paper)

    def test_update_paper(self):
        """Test updating paper fields."""
        existing_paper = Mock(spec=Paper)
        existing_paper.title = "Old Title"
        existing_paper.abstract = "Old Abstract"
        existing_paper.save = Mock()

        new_paper = Mock(spec=Paper)
        new_paper.title = "New Title"
        new_paper.paper_title = "New Paper Title"
        new_paper.abstract = "New Abstract"
        new_paper.paper_publish_date = "2024-01-01"
        new_paper.raw_authors = [{"name": "Author"}]
        new_paper.external_metadata = {"key": "value"}
        new_paper.pdf_url = "https://example.com/paper.pdf"
        new_paper.url = "https://example.com/paper"
        new_paper.is_open_access = True
        new_paper.oa_status = "gold"

        result = self.service._update_paper(existing_paper, new_paper)

        self.assertEqual(existing_paper.title, "New Title")
        self.assertEqual(existing_paper.abstract, "New Abstract")
        existing_paper.save.assert_called_once()
        self.assertEqual(result, existing_paper)

    @patch("paper.ingestion.service.PaperIngestionService.ingest_papers")
    def test_ingest_single_paper_success(self, mock_ingest_papers):
        """Test ingesting a single paper successfully."""
        mock_paper = Mock(spec=Paper)
        mock_ingest_papers.return_value = ([mock_paper], [])

        raw_record = {"id": "test123", "title": "Test Paper"}
        result = self.service.ingest_single_paper(raw_record, IngestionSource.ARXIV)

        self.assertEqual(result, mock_paper)
        mock_ingest_papers.assert_called_once_with(
            [raw_record],
            IngestionSource.ARXIV,
            validate=True,
            save_to_db=True,
            update_existing=False,
        )

    @patch("paper.ingestion.service.PaperIngestionService.ingest_papers")
    def test_ingest_single_paper_failure(self, mock_ingest_papers):
        """Test handling failure when ingesting a single paper."""
        mock_ingest_papers.return_value = (
            [],
            [{"error": "Test error", "id": "test123"}],
        )

        raw_record = {"id": "test123", "title": "Test Paper"}
        result = self.service.ingest_single_paper(raw_record, IngestionSource.ARXIV)

        self.assertIsNone(result)

    def test_ingest_multiple_papers_mixed_results(self):
        """Test ingesting multiple papers with mixed success/failure."""
        with patch(
            "paper.ingestion.service.PaperIngestionService.get_mapper"
        ) as mock_get_mapper:
            mock_mapper = Mock()

            # First record validates and maps successfully
            # Second record fails validation
            # Third record validates but fails mapping
            mock_mapper.validate.side_effect = [True, False, True]

            mock_paper1 = Mock(spec=Paper)
            mock_paper1.doi = None
            mock_paper1.save = Mock()

            mock_mapper.map_to_paper.side_effect = [
                mock_paper1,
                None,  # Won't be called due to validation failure
                None,  # Returns None, triggering "Mapper returned None" error
            ]

            mock_get_mapper.return_value = mock_mapper

            raw_response = [
                {"id": "test1", "title": "Paper 1"},
                {"id": "test2", "title": "Paper 2"},
                {"id": "test3", "title": "Paper 3"},
            ]

            papers, failures = self.service.ingest_papers(
                raw_response, IngestionSource.ARXIV, validate=True, save_to_db=True
            )

            self.assertEqual(len(papers), 1)
            self.assertEqual(len(failures), 2)
            self.assertEqual(failures[0]["error"], "Validation failed")
            self.assertEqual(failures[1]["error"], "Mapper returned None")
