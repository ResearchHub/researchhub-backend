"""
Tests for MedRxiv mapper.
"""

from unittest.mock import PropertyMock, patch

from django.test import TestCase

from hub.models import Hub
from paper.ingestion.mappers.medrxiv import MedRxivMapper
from paper.models import Paper


class TestMedRxivMapper(TestCase):
    """Test cases for MedRxiv mapper using Django TestCase."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = MedRxivMapper()

        # Sample MedRxiv record
        self.sample_record = {
            "title": "COVID-19 vaccine effectiveness in healthcare workers",
            "authors": "Smith, J. A.; Johnson, B. C.; Williams, D. E.",
            "author_corresponding": "Jane A. Smith",
            "author_corresponding_institution": "University Medical Center",
            "doi": "10.1101/2024.12.31.24319876",
            "date": "2025-01-01",
            "version": "2",
            "type": "new results",
            "license": "cc_by",
            "category": "epidemiology",
            "jatsxml": (
                "https://www.medrxiv.org/content/early/2025/01/01/"
                "2024.12.31.24319876.source.xml"
            ),
            "abstract": (
                "This study evaluates the effectiveness of COVID-19 vaccines "
                "in healthcare workers during the omicron variant surge."
            ),
            "funder": "NIH",
            "published": "NA",
            "server": "medRxiv",
        }

    def test_validate_valid_record(self):
        """Test validation of a valid paper record."""
        valid_record = {
            "doi": "10.1101/2024.12.31.24319876",
            "title": "A valid medical research title",
            "authors": "Author1; Author2",
            "date": "2025-01-01",
            "abstract": (
                "This is a valid abstract about medical research that contains "
                "more than fifty characters to pass validation."
            ),
        }

        self.assertTrue(self.mapper.validate(valid_record))

    def test_map_to_paper(self):
        """Test mapping MedRxiv record to Paper model instance."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check that we get a Paper instance
        self.assertIsInstance(paper, Paper)

        # Check core fields
        self.assertEqual(paper.doi, "10.1101/2024.12.31.24319876")
        self.assertEqual(
            paper.url,
            "https://www.medrxiv.org/content/10.1101/2024.12.31.24319876v2",
        )
        self.assertEqual(
            paper.pdf_url,
            "https://www.medrxiv.org/content/10.1101/2024.12.31.24319876v2.full.pdf",
        )
        self.assertEqual(
            paper.title, "COVID-19 vaccine effectiveness in healthcare workers"
        )
        self.assertEqual(paper.paper_title, paper.title)
        self.assertEqual(paper.external_source, "medrxiv")
        self.assertTrue(paper.retrieved_from_external_source)
        self.assertEqual(paper.pdf_license, "cc-by")
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")

        # Check date parsing
        self.assertEqual(str(paper.paper_publish_date), "2025-01-01")

    def test_parse_author_names(self):
        """Test author name parsing stored in Paper instance."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check raw_authors field on Paper model
        raw_authors = paper.raw_authors
        self.assertIsInstance(raw_authors, list)
        self.assertEqual(len(raw_authors), 3)

        # Check first author
        first_author = raw_authors[0]
        self.assertEqual(first_author["full_name"], "Smith, J. A.")
        self.assertEqual(first_author["last_name"], "Smith")
        self.assertEqual(first_author["first_name"], "J.")
        self.assertEqual(first_author["middle_name"], "A.")

        # Check second author
        second_author = raw_authors[1]
        self.assertEqual(second_author["full_name"], "Johnson, B. C.")
        self.assertEqual(second_author["last_name"], "Johnson")
        self.assertEqual(second_author["first_name"], "B.")
        self.assertEqual(second_author["middle_name"], "C.")

        # Check third author
        third_author = raw_authors[2]
        self.assertEqual(third_author["full_name"], "Williams, D. E.")
        self.assertEqual(third_author["last_name"], "Williams")
        self.assertEqual(third_author["first_name"], "D.")
        self.assertEqual(third_author["middle_name"], "E.")

    def test_compute_urls(self):
        """Test URL computation from DOI and version for MedRxiv."""
        paper = self.mapper.map_to_paper(self.sample_record)

        expected_pdf = (
            "https://www.medrxiv.org/content/10.1101/2024.12.31.24319876v2.full.pdf"
        )
        expected_html = "https://www.medrxiv.org/content/10.1101/2024.12.31.24319876v2"

        self.assertEqual(paper.pdf_url, expected_pdf)
        self.assertEqual(paper.url, expected_html)

    def test_map_to_hubs(self):
        """
        Test map_to_hubs returns the MedRxiv hub.
        """
        # Arrange
        hub, _ = Hub.objects.get_or_create(
            slug="medrxiv",
            defaults={
                "name": "MedRxiv",
                "namespace": Hub.Namespace.JOURNAL,
            },
        )
        mapper = MedRxivMapper()
        mapper._hub = hub
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(paper, self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], hub)
        self.assertEqual(hubs[0].slug, "medrxiv")
        self.assertEqual(hubs[0].namespace, Hub.Namespace.JOURNAL)

    @patch.object(MedRxivMapper, "preprint_hub", new_callable=PropertyMock)
    def test_map_to_hubs_without_existing_hub(self, mock_preprint_hub):
        """
        Test map_to_hubs returns empty list when MedRxiv hub doesn't exist.
        """
        # Arrange
        mock_preprint_hub.return_value = None
        mapper = MedRxivMapper()
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(paper, self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 0)
        self.assertEqual(hubs, [])

    def test_medrxiv_specific_config(self):
        """Test MedRxiv-specific configuration."""
        self.assertEqual(self.mapper.default_server, "medrxiv")
        self.assertEqual(self.mapper.hub_slug, "medrxiv")
