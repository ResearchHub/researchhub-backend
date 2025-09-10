"""
Tests for BioRxiv mapper.
"""

from unittest.mock import patch

from django.test import TestCase

from paper.ingestion.mappers.biorxiv import BioRxivMapper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author


class TestBioRxivMapper(TestCase):
    """Test cases for BioRxiv mapper using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = BioRxivMapper()

        # Sample BioRxiv record
        self.sample_record = {
            "title": "Persistent DNA methylation and downregulation",
            "authors": "Gomez Cuautle, D. D.; Rossi, A. R.; Villarreal, A.",
            "author_corresponding": "Alberto Javier Ramos",
            "author_corresponding_institution": "CONICET",
            "doi": "10.1101/2024.12.31.630767",
            "date": "2025-01-01",
            "version": "1",
            "type": "new results",
            "license": "cc_no",
            "category": "neuroscience",
            "jatsxml": "https://www.biorxiv.org/content/early/2025/01/01/2024.12.31.630767.source.xml",
            "abstract": (
                "This is a valid abstract that contains more than fifty "
                "characters to pass validation."
            ),
            "funder": "NA",
            "published": "NA",
            "server": "bioRxiv",
        }

    def test_validate_valid_record(self):
        """Test validation of a valid paper record."""
        valid_record = {
            "doi": "10.1101/2024.12.31.630767",
            "title": "A valid title that is long enough",
            "authors": "Author1; Author2",
            "date": "2025-01-01",
            "abstract": (
                "This is a valid abstract that contains more than fifty "
                "characters to pass validation."
            ),
        }

        self.assertTrue(self.mapper.validate(valid_record))

    def test_validate_invalid_records(self):
        """Test validation rejects invalid records."""
        # Missing required field
        record_missing_doi = {
            "title": "A valid title",
            "authors": "Author1",
            "date": "2025-01-01",
        }
        self.assertFalse(self.mapper.validate(record_missing_doi))

        # Invalid date format
        record_bad_date = {
            "doi": "10.1101/2024.12.31.630767",
            "title": "A valid title",
            "authors": "Author1",
            "date": "01-01-2025",  # Wrong format
        }
        self.assertFalse(self.mapper.validate(record_bad_date))

    def test_map_to_paper(self):
        """Test mapping BioRxiv record to Paper model instance."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check that we get a Paper instance
        self.assertIsInstance(paper, Paper)

        # Check core fields
        self.assertEqual(paper.doi, "10.1101/2024.12.31.630767")
        self.assertEqual(
            paper.url,
            "https://www.biorxiv.org/content/10.1101/2024.12.31.630767v1",
        )
        self.assertEqual(
            paper.pdf_url,
            "https://www.biorxiv.org/content/10.1101/2024.12.31.630767v1.full.pdf",
        )
        self.assertEqual(paper.title, "Persistent DNA methylation and downregulation")
        self.assertEqual(paper.paper_title, paper.title)
        self.assertEqual(paper.external_source, "biorxiv")
        self.assertTrue(paper.retrieved_from_external_source)
        self.assertEqual(paper.pdf_license, "cc_no")
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")

        # Check date parsing
        self.assertEqual(str(paper.paper_publish_date), "2025-01-01")

        # Check external metadata
        self.assertEqual(
            paper.external_metadata["biorxiv_doi"], "10.1101/2024.12.31.630767"
        )
        self.assertEqual(paper.external_metadata["version"], "1")
        self.assertEqual(paper.external_metadata["server"], "bioRxiv")
        self.assertEqual(paper.external_metadata["category"], "neuroscience")

    def test_parse_author_names(self):
        """Test author name parsing stored in Paper instance."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check raw_authors field on Paper model
        raw_authors = paper.raw_authors
        self.assertIsInstance(raw_authors, list)
        self.assertEqual(len(raw_authors), 3)

        # Check first author (with middle initial)
        first_author = raw_authors[0]
        self.assertEqual(first_author["full_name"], "Gomez Cuautle, D. D.")
        self.assertEqual(first_author["last_name"], "Gomez Cuautle")
        self.assertEqual(first_author["first_name"], "D.")
        self.assertEqual(first_author["middle_name"], "D.")

        # Check second author
        second_author = raw_authors[1]
        self.assertEqual(second_author["full_name"], "Rossi, A. R.")
        self.assertEqual(second_author["last_name"], "Rossi")
        self.assertEqual(second_author["first_name"], "A.")
        self.assertEqual(second_author["middle_name"], "R.")

        # Check third author (single initial)
        third_author = raw_authors[2]
        self.assertEqual(third_author["full_name"], "Villarreal, A.")
        self.assertEqual(third_author["last_name"], "Villarreal")
        self.assertEqual(third_author["first_name"], "A.")
        self.assertEqual(third_author["middle_name"], "")

    def test_map_batch(self):
        """Test batch mapping of multiple records."""
        records = [
            self.sample_record,
            {
                "doi": "10.1101/2024.12.31.629756",
                "title": "Another valid paper title",
                "authors": "Author1; Author2",
                "date": "2025-01-02",
                "version": "2",
                "server": "medRxiv",
                "abstract": (
                    "Another abstract with sufficient content to pass "
                    "validation requirements"
                ),
            },
        ]

        mapped_papers = self.mapper.map_batch(records)

        self.assertEqual(len(mapped_papers), 2)

        # Check that we get Paper instances
        self.assertIsInstance(mapped_papers[0], Paper)
        self.assertIsInstance(mapped_papers[1], Paper)

        # Check fields
        self.assertEqual(mapped_papers[0].doi, "10.1101/2024.12.31.630767")
        self.assertEqual(mapped_papers[1].doi, "10.1101/2024.12.31.629756")
        self.assertEqual(mapped_papers[0].external_source, "biorxiv")
        self.assertEqual(mapped_papers[1].external_source, "medrxiv")

    def test_compute_urls(self):
        """Test URL computation from DOI and version."""
        paper = self.mapper.map_to_paper(self.sample_record)

        expected_pdf = (
            "https://www.biorxiv.org/content/10.1101/2024.12.31.630767v1.full.pdf"
        )
        expected_html = "https://www.biorxiv.org/content/10.1101/2024.12.31.630767v1"

        self.assertEqual(paper.pdf_url, expected_pdf)
        self.assertEqual(paper.url, expected_html)

    def test_map_to_author(self):
        """Test mapping author data to Author model instance."""
        author_data = {
            "first_name": "John",
            "last_name": "Doe",
            "middle_name": "M.",
            "raw_name": "Doe, John M.",
            "affiliations": ["University of Example"],
        }

        author = self.mapper.map_to_author(author_data)

        # Check that we get an Author instance
        self.assertIsInstance(author, Author)

        # Check mapped fields
        self.assertEqual(author.first_name, "John")
        self.assertEqual(author.last_name, "Doe")
        self.assertEqual(author.created_source, Author.SOURCE_RESEARCHHUB)

        # Check additional attributes
        self.assertEqual(author._middle_name, "M.")
        self.assertEqual(author._raw_name, "Doe, John M.")
        self.assertEqual(author._affiliations, ["University of Example"])

    def test_paper_model_instance_not_saved_by_default(self):
        """Test that map_to_paper returns unsaved Paper instance."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Paper should not have an ID (not saved to database)
        self.assertIsNone(paper.id)

        # Verify paper is not in database
        self.assertFalse(Paper.objects.filter(doi="10.1101/2024.12.31.630767").exists())

        # But we can save it if needed
        paper.save()
        self.assertIsNotNone(paper.id)
        self.assertTrue(Paper.objects.filter(doi="10.1101/2024.12.31.630767").exists())
