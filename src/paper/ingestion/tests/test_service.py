"""Tests for the PaperIngestionService."""

import json
from unittest.mock import MagicMock, patch

from django.test import TestCase

from paper.ingestion.exceptions import IngestionError
from paper.ingestion.service import PaperIngestionService
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author


class TestPaperIngestionService(TestCase):
    """Test cases for PaperIngestionService."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = PaperIngestionService()
        self.sample_biorxiv_data = [
            {
                "doi": "10.1101/2024.01.01.123456",
                "title": "Test Paper Title",
                "abstract": "Test abstract content",
                "date": "2024-01-01",
                "category": "neuroscience",
                "published": "NA",
                "server": "biorxiv",
                "authors": "Doe, John; Smith, Jane",  # BioRxiv format: semicolon-separated
            }
        ]

    def test_process_raw_response_with_valid_biorxiv_data(self):
        """Test processing valid BioRxiv data."""
        papers, authors = self.service.process_raw_response(
            self.sample_biorxiv_data, "biorxiv", save=False
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1101/2024.01.01.123456")
        self.assertEqual(papers[0].title, "Test Paper Title")
        self.assertEqual(papers[0].abstract, "Test abstract content")

        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0].first_name, "John")
        self.assertEqual(authors[0].last_name, "Doe")
        self.assertEqual(authors[1].first_name, "Jane")
        self.assertEqual(authors[1].last_name, "Smith")

    def test_process_raw_response_with_invalid_source(self):
        """Test processing with an unsupported source."""
        with self.assertRaises(IngestionError) as context:
            self.service.process_raw_response(
                self.sample_biorxiv_data, "unknown_source", save=False
            )

        self.assertIn(
            "No mapper found for source: unknown_source", str(context.exception)
        )

    def test_process_raw_response_skips_invalid_records(self):
        """Test that invalid records are skipped during processing."""
        invalid_data = [
            {"title": "Missing DOI"},  # Invalid - no DOI
            {
                "doi": "10.1101/2024.01.02.789012",
                "title": "Valid Paper",
                "abstract": "Valid abstract",
                "date": "2024-01-02",
                "category": "biology",
                "published": "NA",
                "server": "biorxiv",
                "authors": "Author, Test",  # BioRxiv format
            },
        ]

        papers, authors = self.service.process_raw_response(
            invalid_data, "biorxiv", save=False
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1101/2024.01.02.789012")
        self.assertEqual(len(authors), 1)

    def test_process_raw_response_with_save_creates_paper(self):
        """Test that papers are saved when save=True."""
        papers, authors = self.service.process_raw_response(
            self.sample_biorxiv_data, "biorxiv", save=True
        )

        self.assertEqual(len(papers), 1)
        saved_paper = papers[0]

        # Verify paper was saved to database
        self.assertIsNotNone(saved_paper.id)
        db_paper = Paper.objects.get(doi="10.1101/2024.01.01.123456")
        self.assertEqual(db_paper.title, "Test Paper Title")

        # Verify authors were saved
        self.assertEqual(len(authors), 2)
        for author in authors:
            self.assertIsNotNone(author.id)

        # Verify authorships were created
        authorships = Authorship.objects.filter(paper=db_paper)
        self.assertEqual(authorships.count(), 2)

        # Check first author position
        first_authorship = authorships.filter(author__first_name="John").first()
        self.assertEqual(
            first_authorship.author_position, Authorship.FIRST_AUTHOR_POSITION
        )

        # Check last author position
        last_authorship = authorships.filter(author__first_name="Jane").first()
        self.assertEqual(
            last_authorship.author_position, Authorship.LAST_AUTHOR_POSITION
        )

    def test_process_raw_response_prevents_duplicate_papers(self):
        """Test that duplicate papers are not created."""
        # Process and save the first time
        papers1, _ = self.service.process_raw_response(
            self.sample_biorxiv_data, "biorxiv", save=True
        )

        # Process and save the second time with same DOI
        papers2, _ = self.service.process_raw_response(
            self.sample_biorxiv_data, "biorxiv", save=True
        )

        # Should return the existing paper, not create a new one
        self.assertEqual(papers1[0].id, papers2[0].id)

        # Verify only one paper exists in database
        paper_count = Paper.objects.filter(doi="10.1101/2024.01.01.123456").count()
        self.assertEqual(paper_count, 1)

    def test_process_raw_response_with_medrxiv_uses_biorxiv_mapper(self):
        """Test that MedRxiv data uses the BioRxiv mapper."""
        medrxiv_data = [
            {
                "doi": "10.1101/2024.01.03.456789",
                "title": "MedRxiv Paper",
                "abstract": "Medical research abstract",
                "date": "2024-01-03",
                "category": "medicine",
                "published": "NA",
                "server": "medrxiv",
                "authors": "Medical, Dr.",  # BioRxiv format
            }
        ]

        papers, authors = self.service.process_raw_response(
            medrxiv_data, "medrxiv", save=False
        )

        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0].doi, "10.1101/2024.01.03.456789")
        self.assertEqual(papers[0].title, "MedRxiv Paper")

    def test_process_raw_response_handles_processing_errors(self):
        """Test that processing errors are handled gracefully."""
        # Mock mapper to raise an exception
        mock_mapper = MagicMock()
        mock_mapper.validate.return_value = True
        mock_mapper.map_to_paper.side_effect = Exception("Mapping failed")

        self.service.mappers["biorxiv"] = mock_mapper

        papers, authors = self.service.process_raw_response(
            self.sample_biorxiv_data, "biorxiv", save=False
        )

        # Should return empty lists due to error
        self.assertEqual(len(papers), 0)
        self.assertEqual(len(authors), 0)

    def test_find_or_create_author_finds_existing(self):
        """Test that existing authors are found and reused."""
        # Create an existing author
        existing_author = Author.objects.create(first_name="John", last_name="Doe")

        # Create a new author object with same name
        new_author = Author(first_name="John", last_name="Doe")

        # Should find the existing author
        result = self.service._find_or_create_author(new_author)

        self.assertEqual(result.id, existing_author.id)
        self.assertEqual(result.first_name, "John")
        self.assertEqual(result.last_name, "Doe")

    def test_find_or_create_author_creates_new(self):
        """Test that new authors are created when not found."""
        new_author = Author(first_name="New", last_name="Author")

        # Should create a new author
        result = self.service._find_or_create_author(new_author)

        self.assertIsNotNone(result.id)
        self.assertEqual(result.first_name, "New")
        self.assertEqual(result.last_name, "Author")

        # Verify it was saved to database
        db_author = Author.objects.get(id=result.id)
        self.assertEqual(db_author.first_name, "New")

    def test_process_raw_response_with_multiple_authors_sets_positions(self):
        """Test that author positions are correctly set for multiple authors."""
        data_with_many_authors = [
            {
                "doi": "10.1101/2024.01.04.111111",
                "title": "Multi-Author Paper",
                "abstract": "Abstract",
                "date": "2024-01-04",
                "category": "biology",
                "published": "NA",
                "server": "biorxiv",
                "authors": "Author, First; One, Middle Author; Two, Middle Author; Author, Last",  # BioRxiv format
            }
        ]

        papers, _ = self.service.process_raw_response(
            data_with_many_authors, "biorxiv", save=True
        )

        paper = papers[0]
        authorships = Authorship.objects.filter(paper=paper).order_by("id")

        self.assertEqual(authorships.count(), 4)

        # Check positions
        positions = [a.author_position for a in authorships]
        self.assertEqual(positions[0], Authorship.FIRST_AUTHOR_POSITION)
        self.assertEqual(positions[1], Authorship.MIDDLE_AUTHOR_POSITION)
        self.assertEqual(positions[2], Authorship.MIDDLE_AUTHOR_POSITION)
        self.assertEqual(positions[3], Authorship.LAST_AUTHOR_POSITION)
