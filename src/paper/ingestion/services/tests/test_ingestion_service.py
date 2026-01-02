"""
Tests for the paper ingestion service.
"""

from unittest.mock import Mock, patch

from django.test import TestCase

from institution.models import Institution
from paper.ingestion.constants import IngestionSource
from paper.ingestion.services import PaperIngestionService
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author


class TestPaperIngestionService(TestCase):
    """Test cases for PaperIngestionService."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_arxiv_mapper = Mock()
        self.mock_biorxiv_mapper = Mock()
        self.mock_chemrxiv_mapper = Mock()

        self.mappers = {
            IngestionSource.ARXIV: self.mock_arxiv_mapper,
            IngestionSource.BIORXIV: self.mock_biorxiv_mapper,
            IngestionSource.CHEMRXIV: self.mock_chemrxiv_mapper,
        }

        self.service = PaperIngestionService(self.mappers)

    def test_get_mappers(self):
        """Test getting mappers returns the provided mappers."""
        # Test getting each mapper type
        arxiv_mapper = self.service.get_mapper(IngestionSource.ARXIV)
        self.assertIs(arxiv_mapper, self.mock_arxiv_mapper)

        biorxiv_mapper = self.service.get_mapper(IngestionSource.BIORXIV)
        self.assertIs(biorxiv_mapper, self.mock_biorxiv_mapper)

        chemrxiv_mapper = self.service.get_mapper(IngestionSource.CHEMRXIV)
        self.assertIs(chemrxiv_mapper, self.mock_chemrxiv_mapper)

        # Test that same mapper instance is returned
        arxiv_mapper2 = self.service.get_mapper(IngestionSource.ARXIV)
        self.assertIs(arxiv_mapper, arxiv_mapper2)

    def test_get_mapper_invalid_source(self):
        """Test that invalid source raises ValueError."""
        # Create service with limited mappers
        limited_service = PaperIngestionService(
            {IngestionSource.ARXIV: self.mock_arxiv_mapper}
        )
        with self.assertRaises(ValueError) as context:
            limited_service.get_mapper(IngestionSource.BIORXIV)
        self.assertIn("Unsupported ingestion source", str(context.exception))

    def test_ingest_papers_empty_response(self):
        """Test ingesting empty response returns empty lists."""
        papers, failures = self.service.ingest_papers([], IngestionSource.ARXIV)
        self.assertEqual(papers, [])
        self.assertEqual(failures, [])

    def test_ingest_papers_validation_failure(self):
        """Test handling of validation failures."""
        # Configure the mock mapper for this test
        self.mock_arxiv_mapper.validate.return_value = False

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, validate=True
        )

        self.assertEqual(len(papers), 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error"], "Validation failed")
        self.assertEqual(failures[0]["id"], "test123")

    @patch("paper.ingestion.services.PaperIngestionService._save_paper")
    def test_ingest_papers_with_save(self, mock_save_paper):
        """Test ingestion with database save."""
        mock_paper = Mock(spec=Paper)
        mock_paper.id = 1
        mock_paper.title = "Test Paper"
        mock_paper.doi = "10.1234/test"

        mock_saved_paper = Mock(spec=Paper)
        mock_saved_paper.id = 1
        mock_saved_paper.title = "Test Paper"

        mock_unified_document = Mock()
        mock_hubs = Mock()
        mock_hubs.add = Mock()
        mock_unified_document.hubs = mock_hubs
        mock_saved_paper.unified_document = mock_unified_document

        mock_save_paper.return_value = mock_saved_paper

        # Configure the mock mapper for this test
        self.mock_arxiv_mapper.validate.return_value = True
        self.mock_arxiv_mapper.map_to_paper.return_value = mock_paper
        self.mock_arxiv_mapper.map_to_hubs.return_value = []

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        mock_save_paper.assert_called_once_with(mock_paper)

    def test_ingest_papers_mapping_exception(self):
        """Test handling of exceptions during mapping."""
        # Configure the mock mapper for this test
        self.mock_arxiv_mapper.validate.return_value = True
        self.mock_arxiv_mapper.map_to_paper.side_effect = Exception("Mapping error")

        raw_response = [{"id": "test123", "title": "Test Paper"}]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV
        )

        self.assertEqual(len(papers), 0)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["error"], "Mapping error")
        self.assertEqual(failures[0]["id"], "test123")

    @patch(
        "paper.ingestion.services.PaperIngestionService._trigger_pdf_download_if_needed"
    )
    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_new(self, mock_filter, mock_trigger_pdf):
        """Test saving a new paper."""
        mock_filter.return_value.first.return_value = None

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"
        mock_paper.id = None
        mock_paper.title = "New Paper"
        mock_paper.save = Mock()

        result = self.service._save_paper(mock_paper)

        mock_paper.save.assert_called_once()
        self.assertEqual(result, mock_paper)
        # PDF download should be triggered for new papers
        mock_trigger_pdf.assert_called_once_with(mock_paper, pdf_url_changed=True)

    @patch(
        "paper.ingestion.services.PaperIngestionService._trigger_pdf_download_if_needed"
    )
    @patch("paper.ingestion.services.PaperIngestionService._update_paper")
    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_existing_no_update(
        self, mock_filter, mock_update, mock_trigger_pdf
    ):
        """Test handling existing paper without update."""
        existing_paper = Mock(spec=Paper)
        existing_paper.id = 1
        existing_paper.doi = "10.1234/test"
        existing_paper.pdf_url = "https://example.com/old.pdf"
        mock_filter.return_value.first.return_value = existing_paper

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"
        mock_paper.pdf_url = "https://example.com/old.pdf"  # Same URL
        mock_paper.save = Mock()

        # Mock _update_paper to return the existing paper with no PDF change
        mock_update.return_value = (existing_paper, False)

        result = self.service._save_paper(mock_paper)

        mock_paper.save.assert_not_called()
        self.assertEqual(result, existing_paper)
        # PDF download triggered with pdf_url_changed=False
        mock_trigger_pdf.assert_called_once_with(existing_paper, pdf_url_changed=False)

    @patch(
        "paper.ingestion.services.PaperIngestionService._trigger_pdf_download_if_needed"
    )
    @patch("paper.ingestion.services.PaperIngestionService._update_paper")
    @patch("paper.models.Paper.objects.filter")
    def test_save_paper_existing_with_update(
        self, mock_filter, mock_update, mock_trigger_pdf
    ):
        """Test updating an existing paper."""
        existing_paper = Mock(spec=Paper)
        existing_paper.id = 1
        existing_paper.doi = "10.1234/test"
        mock_filter.return_value.first.return_value = existing_paper

        updated_paper = Mock(spec=Paper)
        mock_update.return_value = (updated_paper, True)

        mock_paper = Mock(spec=Paper)
        mock_paper.doi = "10.1234/test"

        result = self.service._save_paper(mock_paper)

        mock_update.assert_called_once_with(existing_paper, mock_paper)
        self.assertEqual(result, updated_paper)
        # PDF download triggered with pdf_url_changed=True
        mock_trigger_pdf.assert_called_once_with(updated_paper, pdf_url_changed=True)

    def test_update_paper(self):
        """Test updating paper fields."""
        existing_paper = Mock(spec=Paper)
        existing_paper.title = "Old Title"
        existing_paper.abstract = "Old Abstract"
        existing_paper.external_source = "old_source"
        existing_paper.external_metadata = {"metrics": {"x": 100}}
        existing_paper.pdf_url = "https://example.com/old.pdf"
        existing_paper.save = Mock()

        new_paper = Mock(spec=Paper)
        new_paper.title = "New Title"
        new_paper.paper_title = "New Paper Title"
        new_paper.abstract = "New Abstract"
        new_paper.paper_publish_date = "2024-01-01"
        new_paper.raw_authors = [{"name": "Author"}]
        new_paper.external_metadata = {"key": "value"}
        new_paper.external_source = "chemrxiv"
        new_paper.external_metadata = {"external_id": "12345"}
        new_paper.pdf_url = "https://example.com/paper.pdf"
        new_paper.url = "https://example.com/paper"
        new_paper.is_open_access = True
        new_paper.oa_status = "gold"

        result, pdf_url_changed = self.service._update_paper(existing_paper, new_paper)

        self.assertEqual(existing_paper.title, "New Title")
        self.assertEqual(existing_paper.abstract, "New Abstract")
        self.assertEqual(existing_paper.external_source, "chemrxiv")
        self.assertEqual(
            existing_paper.external_metadata,
            {"metrics": {"x": 100}, "external_id": "12345"},
        )
        existing_paper.save.assert_called_once()
        self.assertEqual(result, existing_paper)
        # PDF URL changed from old.pdf to paper.pdf
        self.assertTrue(pdf_url_changed)

    @patch("paper.ingestion.services.PaperIngestionService.ingest_papers")
    def test_ingest_single_paper_success(self, mock_ingest_papers):
        """Test ingesting a single paper successfully."""
        mock_paper = Mock(spec=Paper)
        mock_ingest_papers.return_value = ([mock_paper], [])

        raw_record = {"id": "test123", "title": "Test Paper"}
        result = self.service.ingest_single_paper(raw_record, IngestionSource.ARXIV)

        self.assertEqual(result, mock_paper)
        mock_ingest_papers.assert_called_once_with(
            [raw_record], IngestionSource.ARXIV, validate=True
        )

    @patch("paper.ingestion.services.PaperIngestionService.ingest_papers")
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
        # First record validates and maps successfully
        # Second record fails validation
        # Third record validates but fails mapping
        self.mock_arxiv_mapper.validate.side_effect = [True, False, True]

        mock_paper1 = Mock(spec=Paper)
        mock_paper1.id = 1
        mock_paper1.doi = None
        mock_paper1.save = Mock()

        mock_unified_document = Mock()
        mock_hubs = Mock()
        mock_hubs.add = Mock()
        mock_unified_document.hubs = mock_hubs
        mock_paper1.unified_document = mock_unified_document

        self.mock_arxiv_mapper.map_to_paper.side_effect = [
            mock_paper1,
            None,  # Won't be called due to validation failure
            None,  # Returns None, triggering "Mapper returned None" error
        ]

        self.mock_arxiv_mapper.map_to_hubs.return_value = []

        raw_response = [
            {"id": "test1", "title": "Paper 1"},
            {"id": "test2", "title": "Paper 2"},
            {"id": "test3", "title": "Paper 3"},
        ]

        papers, failures = self.service.ingest_papers(
            raw_response, IngestionSource.ARXIV, validate=True
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0]["error"], "Validation failed")
        self.assertEqual(failures[1]["error"], "Mapper returned None")

    def test_create_authors_and_institutions_with_orcid(self):
        """Test creating authors and institutions with ORCID IDs."""
        # Create a real paper
        paper = Paper.objects.create(
            title="Test Paper",
            paper_title="Test Paper",
            doi="10.1234/chemrxiv.test",
            external_source="chemrxiv",
        )

        # Create mock mapper that returns model instances
        mock_mapper = Mock()

        # Mock authors
        author1 = Author(
            first_name="John",
            last_name="Doe",
            orcid_id="0000-0001-2345-6789",
            created_source=Author.SOURCE_RESEARCHHUB,
        )
        author2 = Author(
            first_name="Jane",
            last_name="Smith",
            orcid_id="0000-0002-3456-7890",
            created_source=Author.SOURCE_RESEARCHHUB,
        )
        mock_mapper.map_to_authors.return_value = [author1, author2]

        # Mock institutions
        inst1 = Institution(
            openalex_id="chemrxiv_test123",
            ror_id="https://ror.org/test123",
            display_name="Test University",
            country_code="US",
            type="education",
            lineage=[],
            associated_institutions=[],
            display_name_alternatives=[],
        )
        inst2 = Institution(
            openalex_id="chemrxiv_test456",
            ror_id="https://ror.org/test456",
            display_name="Another Institute",
            country_code="UK",
            type="education",
            lineage=[],
            associated_institutions=[],
            display_name_alternatives=[],
        )
        mock_mapper.map_to_institutions.return_value = [inst1, inst2]

        # Mock authorships
        authorship1 = Authorship(
            paper=paper,
            author=author1,
            author_position="first",
            raw_author_name="John Doe",
        )
        authorship1._institutions_to_add = [inst1]

        authorship2 = Authorship(
            paper=paper,
            author=author2,
            author_position="last",
            raw_author_name="Jane Smith",
        )
        authorship2._institutions_to_add = [inst1, inst2]

        mock_mapper.map_to_authorships.return_value = [authorship1, authorship2]

        record = {"id": "test", "authors": []}

        # Call the method
        authors, institutions, authorships = (
            self.service._create_authors_and_institutions(paper, record, mock_mapper)
        )

        # Verify authors were created
        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0].first_name, "John")
        self.assertEqual(authors[0].last_name, "Doe")
        self.assertEqual(authors[0].orcid_id, "0000-0001-2345-6789")
        self.assertEqual(authors[1].first_name, "Jane")
        self.assertEqual(authors[1].last_name, "Smith")

        # Verify institutions were created
        self.assertEqual(len(institutions), 2)
        self.assertEqual(institutions[0].display_name, "Test University")
        self.assertEqual(institutions[0].ror_id, "https://ror.org/test123")
        self.assertEqual(institutions[1].display_name, "Another Institute")

        # Verify authorships were created
        self.assertEqual(len(authorships), 2)
        db_authorships = Authorship.objects.filter(paper=paper)
        self.assertEqual(db_authorships.count(), 2)

        # Check first authorship
        first_authorship = db_authorships.filter(author=authors[0]).first()
        self.assertIsNotNone(first_authorship)
        self.assertEqual(first_authorship.author_position, "first")
        self.assertEqual(first_authorship.institutions.count(), 1)

        # Check second authorship has two institutions
        second_authorship = db_authorships.filter(author=authors[1]).first()
        self.assertIsNotNone(second_authorship)
        self.assertEqual(second_authorship.author_position, "last")
        self.assertEqual(second_authorship.institutions.count(), 2)

        # Verify database persistence
        self.assertEqual(
            Author.objects.filter(orcid_id="0000-0001-2345-6789").count(), 1
        )
        self.assertEqual(
            Institution.objects.filter(ror_id="https://ror.org/test123").count(), 1
        )

    def test_reuse_existing_authors_and_institutions(self):
        """Test that existing authors and institutions are reused."""
        # Create existing author and institution
        existing_author = Author.objects.create(
            first_name="Existing",
            last_name="Author",
            orcid_id="0000-0003-4567-8901",
            created_source=Author.SOURCE_RESEARCHHUB,
        )

        existing_institution = Institution.objects.create(
            openalex_id="existing_inst",
            ror_id="https://ror.org/existing",
            display_name="Existing Institution",
            country_code="US",
            type="education",
            lineage=[],
            associated_institutions=[],
            display_name_alternatives=[],
        )

        # Create a paper
        paper = Paper.objects.create(
            title="Test Paper 2",
            doi="10.1234/chemrxiv.test2",
            external_source="chemrxiv",
        )

        # Mock mapper returns same ORCID and ROR ID as existing
        mock_mapper = Mock()
        # Return empty lists since these already exist
        mock_mapper.map_to_authors.return_value = [existing_author]
        mock_mapper.map_to_institutions.return_value = [existing_institution]

        # Mock authorships
        authorship = Authorship(
            paper=paper,
            author=existing_author,
            author_position="first",
            raw_author_name="Existing Author",
        )
        authorship._institutions_to_add = [existing_institution]
        mock_mapper.map_to_authorships.return_value = [authorship]

        record = {"id": "test2", "authors": []}

        # Call the method
        authors, institutions, authorships = (
            self.service._create_authors_and_institutions(paper, record, mock_mapper)
        )

        # Should reuse existing, not create new
        self.assertEqual(len(authors), 0)  # No new authors created
        self.assertEqual(len(institutions), 0)  # No new institutions created

        # But authorship should be created
        authorship = Authorship.objects.filter(
            paper=paper, author=existing_author
        ).first()
        self.assertIsNotNone(authorship)

        # Verify only one author and institution in database
        self.assertEqual(
            Author.objects.filter(orcid_id="0000-0003-4567-8901").count(), 1
        )
        self.assertEqual(
            Institution.objects.filter(ror_id="https://ror.org/existing").count(), 1
        )

    def test_skip_authors_without_orcid(self):
        """Test that authors without ORCID IDs are skipped."""
        paper = Paper.objects.create(
            title="Test Paper 3",
            doi="10.1234/arxiv.test",
            external_source="arxiv",
        )

        mock_mapper = Mock()
        # Return empty list since we don't create authors without ORCID
        mock_mapper.map_to_authors.return_value = []
        mock_mapper.map_to_institutions.return_value = []
        mock_mapper.map_to_authorships.return_value = []

        record = {"id": "test3", "authors": []}

        # Call the method
        authors, institutions, authorships = (
            self.service._create_authors_and_institutions(paper, record, mock_mapper)
        )

        # Should not create author without ORCID
        self.assertEqual(len(authors), 0)
        self.assertEqual(len(institutions), 0)

        # No authorship should be created
        self.assertEqual(Authorship.objects.filter(paper=paper).count(), 0)

    def test_skip_institutions_without_ror_id(self):
        """Test that institutions without ROR IDs are skipped."""
        paper = Paper.objects.create(
            title="Test Paper 4",
            doi="10.1234/chemrxiv.test4",
            external_source="chemrxiv",
        )

        mock_mapper = Mock()

        # Author with ORCID
        author = Author(
            first_name="Test",
            last_name="Author",
            orcid_id="0000-0004-5678-9012",
            created_source=Author.SOURCE_RESEARCHHUB,
        )
        mock_mapper.map_to_authors.return_value = [author]

        # No institutions (skip those without ROR ID)
        mock_mapper.map_to_institutions.return_value = []

        # Authorship without institutions
        authorship = Authorship(
            paper=paper,
            author=author,
            author_position="first",
            raw_author_name="Test Author",
        )
        authorship._institutions_to_add = []
        mock_mapper.map_to_authorships.return_value = [authorship]

        record = {"id": "test4", "authors": []}

        # Call the method
        authors, institutions, authorships = (
            self.service._create_authors_and_institutions(paper, record, mock_mapper)
        )

        # Author should be created but institution should not
        self.assertEqual(len(authors), 1)
        self.assertEqual(len(institutions), 0)

        # Authorship created but with no institutions
        authorship = Authorship.objects.filter(paper=paper).first()
        self.assertIsNotNone(authorship)
        self.assertEqual(authorship.institutions.count(), 0)

    @patch("paper.tasks.download_pdf")
    def test_pdf_download_triggered_for_arxiv_papers(self, mock_download_pdf):
        """Test that PDF download task is triggered for arXiv papers with pdf_url."""
        # Arrange
        paper = Paper(
            title="Test arXiv Paper",
            doi="10.48550/arXiv.2507.00004",
            abstract="Test abstract",
            external_source="arxiv",
            pdf_url="https://arxiv.org/pdf/2507.00004.pdf",  # NOSONAR - http
        )

        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.return_value = paper
        mock_mapper.map_to_hubs.return_value = []

        service = PaperIngestionService({IngestionSource.ARXIV_OAI: mock_mapper})

        # Act
        papers, failures = service.ingest_papers(
            [{"id": "2507.00004", "title": "Test arXiv Paper"}],
            IngestionSource.ARXIV_OAI,
        )

        # Assert
        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        mock_download_pdf.apply_async.assert_called_once_with(
            (papers[0].id,), priority=5
        )

    @patch("paper.tasks.download_pdf")
    @patch("paper.models.Paper.objects.filter")
    def test_pdf_download_triggered_when_pdf_url_changes(
        self, mock_filter, mock_download_pdf
    ):
        """Test that PDF download is triggered when existing paper has new PDF URL."""
        # Arrange - existing paper with old PDF URL and file
        existing_paper = Paper.objects.create(
            title="Existing arXiv Paper",
            doi="10.48550/arXiv.2507.00006",
            abstract="Test abstract",
            external_source="arxiv",
            pdf_url="https://arxiv.org/pdf/2507.00006v1.pdf",  # Old version
            file="uploads/papers/2024/01/01/old_version.pdf",
            external_metadata={},
        )

        # Mock the filter to return our existing paper
        mock_filter.return_value.first.return_value = existing_paper

        # New paper data with updated PDF URL (new version)
        new_paper = Paper(
            title="Updated arXiv Paper",
            doi="10.48550/arXiv.2507.00006",
            abstract="Updated abstract",
            external_source="arxiv",
            pdf_url="https://arxiv.org/pdf/2507.00006v2.pdf",  # New version
            external_metadata={},
        )

        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.return_value = new_paper
        mock_mapper.map_to_hubs.return_value = []

        service = PaperIngestionService({IngestionSource.ARXIV_OAI: mock_mapper})

        # Act
        papers, failures = service.ingest_papers(
            [{"id": "2507.00006", "title": "Updated arXiv Paper"}],
            IngestionSource.ARXIV_OAI,
        )

        # Assert
        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        # PDF download should be triggered because PDF URL changed
        mock_download_pdf.apply_async.assert_called_once_with(
            (existing_paper.id,), priority=5
        )

    @patch("paper.tasks.download_pdf")
    @patch("paper.models.Paper.objects.filter")
    def test_pdf_download_not_triggered_when_pdf_url_unchanged(
        self, mock_filter, mock_download_pdf
    ):
        """Test that PDF download is NOT triggered when PDF URL stays the same."""
        # Arrange - existing paper with PDF URL and file
        existing_paper = Paper.objects.create(
            title="Existing arXiv Paper",
            doi="10.48550/arXiv.2507.00007",
            abstract="Test abstract",
            external_source="arxiv",
            pdf_url="https://arxiv.org/pdf/2507.00007.pdf",
            file="uploads/papers/2024/01/01/existing.pdf",
            external_metadata={},
        )

        # Mock the filter to return our existing paper
        mock_filter.return_value.first.return_value = existing_paper

        # New paper data with SAME PDF URL (just metadata update)
        new_paper = Paper(
            title="Updated Title Only",
            doi="10.48550/arXiv.2507.00007",
            abstract="Updated abstract",
            external_source="arxiv",
            pdf_url="https://arxiv.org/pdf/2507.00007.pdf",  # Same URL
            external_metadata={},
        )

        mock_mapper = Mock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.return_value = new_paper
        mock_mapper.map_to_hubs.return_value = []

        service = PaperIngestionService({IngestionSource.ARXIV_OAI: mock_mapper})

        # Act
        papers, failures = service.ingest_papers(
            [{"id": "2507.00007", "title": "Updated Title Only"}],
            IngestionSource.ARXIV_OAI,
        )

        # Assert
        self.assertEqual(len(papers), 1)
        self.assertEqual(len(failures), 0)
        # PDF download should NOT be triggered (URL unchanged, file exists)
        mock_download_pdf.apply_async.assert_not_called()
