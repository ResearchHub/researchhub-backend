"""
Tests for OpenAlex mapper.
"""

import json
import os
from unittest.mock import MagicMock

from django.test import TestCase

from hub.models import Hub
from paper.ingestion.mappers.openalex import OpenAlexMapper
from paper.models import Paper


class TestOpenAlexMapper(TestCase):
    """
    Test OpenAlex mapper.
    """

    def setUp(self):
        self.mapper = OpenAlexMapper(None)

        # Load fixture files
        fixtures_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "clients", "fixtures"
        )

        # Read the sample response JSON
        fixtures_path = os.path.join(
            fixtures_dir, "openalex_sample_get_by_doi_response.json"
        )
        with open(fixtures_path, "r") as f:
            self.sample_record = json.load(f)

    def test_validate_valid_record(self):
        """
        Test validation of a valid OpenAlex record.
        """
        # Act
        result = self.mapper.validate(self.sample_record)

        # Assert
        self.assertTrue(result)

    def test_validate_missing_id(self):
        """
        Test validation fails for missing ID.
        """
        # Arrange
        record = {"title": "Test Paper"}

        # Act
        result = self.mapper.validate(record)

        # Assert
        self.assertFalse(result)

    def test_validate_missing_title(self):
        """
        Test validation fails for missing title.
        """
        # Arrange
        record = {"id": "https://openalex.org/W123456"}

        # Act
        result = self.mapper.validate(record)

        # Assert
        self.assertFalse(result)

    def test_validate_invalid_type(self):
        """
        Test validation fails for non-article types.
        """
        # Arrange
        record = {
            "id": "https://openalex.org/W123456",
            "title": "Test Paper",
            "type": "book",
        }

        # Act
        result = self.mapper.validate(record)

        # Assert
        self.assertFalse(result)

    def test_extract_openalex_id(self):
        """
        Test extracting OpenAlex ID from URL.
        """
        # Full URL
        self.assertEqual(
            self.mapper._extract_openalex_id("https://openalex.org/W2741809807"),
            "W2741809807",
        )

        # Just ID
        self.assertEqual(self.mapper._extract_openalex_id("W2741809807"), "W2741809807")

        # Empty string
        self.assertEqual(self.mapper._extract_openalex_id(""), "")

    def test_extract_doi(self):
        """
        Test extracting DOI from URL.
        """
        # Full URL
        self.assertEqual(
            self.mapper._extract_doi("https://doi.org/10.7717/peerj.4375"),
            "10.7717/peerj.4375",
        )

        # Just DOI
        self.assertEqual(
            self.mapper._extract_doi("10.7717/peerj.4375"), "10.7717/peerj.4375"
        )

        # None
        self.assertIsNone(self.mapper._extract_doi(None))

    def test_get_best_date(self):
        """
        Test getting the best available date.
        """
        # With publication_date
        record = {"publication_date": "2018-02-13", "publication_year": 2018}
        self.assertEqual(self.mapper._get_best_date(record), "2018-02-13")

        # Only publication_year
        record = {"publication_year": 2018}
        self.assertEqual(self.mapper._get_best_date(record), "2018-01-01")

        # No dates
        record = {}
        self.assertIsNone(self.mapper._get_best_date(record))

    def test_parse_date(self):
        """
        Test parsing dates.
        """
        # Valid ISO date
        self.assertEqual(self.mapper._parse_date("2018-02-13"), "2018-02-13")

        # Invalid date
        self.assertIsNone(self.mapper._parse_date("invalid"))

        # None
        self.assertIsNone(self.mapper._parse_date(None))

    def test_parse_author_name(self):
        """
        Test parsing author names.
        """
        # First Last
        result = self.mapper._parse_author_name("Heather Piwowar")
        self.assertEqual(result["first_name"], "Heather")
        self.assertEqual(result["middle_name"], "")
        self.assertEqual(result["last_name"], "Piwowar")

        # First Middle Last
        result = self.mapper._parse_author_name("Juan Pablo Alperín")
        self.assertEqual(result["first_name"], "Juan")
        self.assertEqual(result["middle_name"], "Pablo")
        self.assertEqual(result["last_name"], "Alperín")

        # Single name
        result = self.mapper._parse_author_name("Cher")
        self.assertEqual(result["first_name"], "")
        self.assertEqual(result["middle_name"], "")
        self.assertEqual(result["last_name"], "Cher")

    def test_map_to_paper(self):
        """
        Test mapping OpenAlex record to Paper model.
        """
        # Act
        paper = self.mapper.map_to_paper(self.sample_record)

        # Assert
        self.assertIsInstance(paper, Paper)
        self.assertEqual(paper.doi, "10.7717/peerj.4375")
        self.assertEqual(paper.external_source, "openalex")
        self.assertTrue(
            "state of OA" in paper.title or "Open Access articles" in paper.title
        )
        self.assertEqual(paper.paper_publish_date, "2018-02-13")
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")
        self.assertIsNotNone(paper.url)
        self.assertIsNotNone(paper.pdf_url)
        self.assertEqual(paper.openalex_id, "W2741809807")
        self.assertIsNotNone(paper.external_metadata)
        self.assertIsNotNone(paper.external_metadata.get("cited_by_count"))
        self.assertIsNotNone(paper.raw_authors)
        self.assertGreater(len(paper.raw_authors), 0)

    def test_extract_authors(self):
        """
        Test extracting authors from authorships list.
        """
        # Arrange
        authorships = self.sample_record.get("authorships", [])

        # Act
        authors = self.mapper._extract_authors(authorships)

        # Assert
        self.assertGreater(len(authors), 0)
        first_author = authors[0]
        self.assertEqual(first_author["full_name"], "Heather Piwowar")
        self.assertEqual(first_author["first_name"], "Heather")
        self.assertEqual(first_author["last_name"], "Piwowar")
        self.assertIn("orcid", first_author)
        self.assertEqual(first_author["orcid"], "0000-0003-1613-5981")
        self.assertEqual(first_author["position"], 0)
        self.assertIn("affiliations", first_author)
        self.assertGreater(len(first_author["affiliations"]), 0)

    def test_map_to_authors(self):
        """
        Test mapping to Author model instances.
        """
        # Act
        authors = self.mapper.map_to_authors(self.sample_record)

        # Assert
        self.assertGreater(len(authors), 0)
        first_author = authors[0]
        self.assertEqual(first_author.first_name, "Heather")
        self.assertEqual(first_author.last_name, "Piwowar")
        self.assertEqual(first_author.orcid_id, "0000-0003-1613-5981")
        self.assertIsNotNone(first_author.openalex_ids)
        self.assertGreater(len(first_author.openalex_ids), 0)

    def test_map_to_institutions(self):
        """
        Test mapping to Institution model instances.
        """
        # Arrange - sample_record from setUp

        # Act
        institutions = self.mapper.map_to_institutions(self.sample_record)

        # Assert
        self.assertGreater(len(institutions), 0)
        for institution in institutions:
            self.assertIsNotNone(institution.ror_id)
            self.assertIsNotNone(institution.display_name)

    def test_map_to_authorships(self):
        """
        Test mapping to Authorship model instances.
        """
        # Arrange
        paper = Paper(
            doi="10.7717/peerj.4375",
            title="Test Paper",
            external_source="openalex",
        )

        # Act
        authorships = self.mapper.map_to_authorships(paper, self.sample_record)

        # Assert
        self.assertGreater(len(authorships), 0)
        first_authorship = authorships[0]
        self.assertEqual(first_authorship.paper, paper)
        self.assertIsNotNone(first_authorship.raw_author_name)
        self.assertIsNotNone(first_authorship.author_position)
        self.assertTrue(hasattr(first_authorship, "_orcid_id"))
        self.assertIsNotNone(first_authorship._orcid_id)

    def test_map_batch(self):
        """
        Test batch mapping of records.
        """
        # Arrange
        records = [self.sample_record]

        # Act
        papers = self.mapper.map_batch(records)

        # Assert
        self.assertEqual(len(papers), 1)
        self.assertIsInstance(papers[0], Paper)

    def test_map_batch_with_invalid_record(self):
        """
        Test batch mapping skips invalid records.
        """
        # Arrange
        records = [
            self.sample_record,
            {"id": "https://openalex.org/W123", "type": "book"},  # Invalid
        ]

        # Act
        papers = self.mapper.map_batch(records)

        # Assert - Only valid record should be mapped
        self.assertEqual(len(papers), 1)

    def test_map_to_hubs(self):
        """
        Test mapping to Hub instances.
        """
        # Arrange
        paper = Paper(
            doi="10.7717/peerj.4375",
            title="Test Paper",
            external_source="openalex",
        )
        mock_hub = Hub(name="Test Hub", slug="test-hub")
        mock_hub_mapper = MagicMock()
        mock_hub_mapper.map.return_value = [mock_hub]
        mapper = OpenAlexMapper(hub_mapper=mock_hub_mapper)

        # Act
        mapper.map_to_hubs(paper, self.sample_record)

        # Assert
        self.assertTrue(mock_hub_mapper.map.called)
