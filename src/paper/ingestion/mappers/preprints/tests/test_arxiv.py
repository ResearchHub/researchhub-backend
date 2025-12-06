"""
Tests for ArXiv mapper.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hub.models import Hub
from paper.ingestion.mappers import ArXivMapper
from paper.models import Paper


class TestArXivMapper(TestCase):
    """Test ArXiv mapper functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = ArXivMapper(None)

        self.arxiv_hub, _ = Hub.objects.get_or_create(
            slug="arxiv",
            defaults={
                "name": "ArXiv",
                "namespace": Hub.Namespace.JOURNAL,
            },
        )

        # Load fixture files
        fixtures_dir = Path(__file__).parent / "fixtures"

        # Read the sample response XML
        with open(fixtures_dir / "arxiv_sample_response.xml", "r") as f:
            self.sample_response_xml = f.read()

        # Read the empty response XML
        with open(fixtures_dir / "arxiv_empty_response.xml", "r") as f:
            self.empty_response_xml = f.read()

        # Extract individual entries from the sample response
        root = ET.fromstring(self.sample_response_xml)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")

        # First entry (without extras)
        self.sample_xml = ET.tostring(entries[0], encoding="unicode")

        # Second entry (with comment)
        self.sample_xml_with_extras = ET.tostring(entries[1], encoding="unicode")

        # Create parsed records for testing
        self.sample_record = {"raw_xml": self.sample_xml}
        self.sample_with_extras = {"raw_xml": self.sample_xml_with_extras}

    def test_validate_valid_record(self):
        """Test validation of a valid ArXiv record."""
        self.assertTrue(self.mapper.validate(self.sample_record))

    def test_validate_missing_required_fields(self):
        """Test validation fails for missing required fields."""
        # Missing ID
        bad_xml = """<entry xmlns="http://www.w3.org/2005/Atom">
    <title>Test Paper</title>
    <author><name>Test Author</name></author>
  </entry>"""
        record = {"raw_xml": bad_xml}
        self.assertFalse(self.mapper.validate(record))

        # Missing title
        bad_xml = """<entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/2509.10432v1</id>
    <author><name>Test Author</name></author>
  </entry>"""
        record = {"raw_xml": bad_xml}
        self.assertFalse(self.mapper.validate(record))

        # Missing authors
        bad_xml = """<entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/2509.10432v1</id>
    <title>Test Paper</title>
  </entry>"""
        record = {"raw_xml": bad_xml}
        self.assertFalse(self.mapper.validate(record))

    def test_validate_missing_dates(self):
        """Test validation fails when no dates are present."""
        bad_xml = """<entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/2509.10432v1</id>
    <title>Test Paper</title>
    <author><name>Test Author</name></author>
  </entry>"""
        record = {"raw_xml": bad_xml}
        self.assertFalse(self.mapper.validate(record))

    @patch("paper.models.Paper.save")
    def test_map_to_paper(self, mock_save):
        """Test mapping ArXiv record to Paper model."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check basic fields (first entry from fixture)
        self.assertEqual(paper.doi, "10.48550/arXiv.2509.08827")
        self.assertEqual(paper.external_source, "arxiv")
        self.assertEqual(
            paper.title, "A Survey of Reinforcement Learning for Large Reasoning Models"
        )
        self.assertIn("we survey recent advances", paper.abstract)

        # Check dates
        self.assertEqual(paper.paper_publish_date, "2025-09-10")

        # Check authors
        self.assertEqual(len(paper.raw_authors), 3)
        self.assertEqual(paper.raw_authors[0]["full_name"], "Kaiyan Zhang")
        self.assertEqual(paper.raw_authors[0]["first_name"], "Kaiyan")
        self.assertEqual(paper.raw_authors[0]["last_name"], "Zhang")
        self.assertEqual(paper.raw_authors[2]["full_name"], "Bingxiang He")
        self.assertEqual(paper.raw_authors[2]["first_name"], "Bingxiang")
        self.assertEqual(paper.raw_authors[2]["last_name"], "He")

        # Check open access
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")

        # Check URLs
        self.assertEqual(
            paper.pdf_url, "http://arxiv.org/pdf/2509.08827v1"  # NOSONAR - Ignore http
        )
        self.assertEqual(
            paper.url, "http://arxiv.org/abs/2509.08827v1"  # NOSONAR - Ignore http
        )

        # Check external metadata - should only have arxiv_id
        self.assertEqual(paper.external_metadata["external_id"], "2509.08827v1")
        self.assertEqual(len(paper.external_metadata), 1)

        # Check flags
        self.assertTrue(paper.retrieved_from_external_source)

    def test_map_to_paper_with_extras(self):
        """Test mapping ArXiv record with additional fields."""
        paper = self.mapper.map_to_paper(self.sample_with_extras)

        # Check DOI formatting for second entry
        self.assertEqual(paper.doi, "10.48550/arXiv.2509.08817")
        # Verify only arxiv_id is in metadata
        self.assertEqual(paper.external_metadata["external_id"], "2509.08817v1")
        self.assertEqual(len(paper.external_metadata), 1)

    def test_parse_xml_entry(self):
        """Test XML entry parsing."""
        parsed = self.mapper._parse_xml_entry(self.sample_xml)

        # Check basic fields (first entry from fixture)
        self.assertEqual(
            parsed["id"], "http://arxiv.org/abs/2509.08827v1"  # NOSONAR - Ignore http
        )
        self.assertEqual(
            parsed["title"],
            "A Survey of Reinforcement Learning for Large Reasoning Models",
        )
        self.assertIn("we survey recent advances", parsed["summary"])
        self.assertEqual(parsed["published"], "2025-09-10T17:59:43Z")
        self.assertEqual(parsed["updated"], "2025-09-10T17:59:43Z")

        # Check authors
        self.assertEqual(len(parsed["authors"]), 3)
        self.assertEqual(parsed["authors"][0]["name"], "Kaiyan Zhang")
        self.assertEqual(parsed["authors"][2]["name"], "Bingxiang He")

        # Check categories
        self.assertEqual(parsed["categories"], ["cs.CL", "cs.AI", "cs.LG"])
        self.assertEqual(parsed["primary_category"], "cs.CL")

        # Check links
        self.assertEqual(
            parsed["links"]["alternate"],
            "http://arxiv.org/abs/2509.08827v1",  # NOSONAR - Ignore http
        )
        self.assertEqual(
            parsed["links"]["pdf"],
            "http://arxiv.org/pdf/2509.08827v1",  # NOSONAR - Ignore http
        )

    def test_extract_arxiv_id(self):
        """Test ArXiv ID extraction from URLs."""
        # From abs URL
        id_url = "https://arxiv.org/abs/2509.10432v1"
        self.assertEqual(self.mapper._extract_arxiv_id(id_url), "2509.10432v1")

        # From pdf URL
        id_url = "https://arxiv.org/pdf/2509.10432v1.pdf"
        self.assertEqual(self.mapper._extract_arxiv_id(id_url), "2509.10432v1")

        # Already just an ID
        self.assertEqual(self.mapper._extract_arxiv_id("2509.10432v1"), "2509.10432v1")

        # Empty string
        self.assertEqual(self.mapper._extract_arxiv_id(""), "")

    def test_format_arxiv_doi(self):
        """Test ArXiv DOI formatting."""
        # With version
        self.assertEqual(
            self.mapper._format_arxiv_doi("2509.10432v1"), "10.48550/arXiv.2509.10432"
        )

        # Without version
        self.assertEqual(
            self.mapper._format_arxiv_doi("2509.10432"), "10.48550/arXiv.2509.10432"
        )

        # Empty string
        self.assertEqual(self.mapper._format_arxiv_doi(""), "")

    def test_parse_date(self):
        """Test date parsing from ISO format."""
        # Valid ISO date
        date = self.mapper._parse_date("2025-09-12T17:38:46Z")
        self.assertEqual(date, "2025-09-12")

        # Another valid ISO date
        date = self.mapper._parse_date("2025-01-01T00:00:00Z")
        self.assertEqual(date, "2025-01-01")

        # Invalid date
        date = self.mapper._parse_date("invalid-date")
        self.assertIsNone(date)

        # None date
        date = self.mapper._parse_date(None)
        self.assertIsNone(date)

    def test_get_best_date(self):
        """Test getting the best available date."""
        # Both dates present - should use published
        record = {
            "published": "2025-09-12T17:38:46Z",
            "updated": "2025-09-13T10:00:00Z",
        }
        date = self.mapper._get_best_date(record)
        self.assertEqual(date, "2025-09-12")

        # Only updated date
        record = {"updated": "2025-09-13T10:00:00Z"}
        date = self.mapper._get_best_date(record)
        self.assertEqual(date, "2025-09-13")

    def test_parse_author_name(self):
        """Test author name parsing."""
        # Simple two-part name
        name_parts = self.mapper._parse_author_name("John Doe")
        self.assertEqual(name_parts["first_name"], "John")
        self.assertEqual(name_parts["last_name"], "Doe")
        self.assertEqual(name_parts["middle_name"], "")

        # Three-part name
        name_parts = self.mapper._parse_author_name("John Q. Doe")
        self.assertEqual(name_parts["first_name"], "John")
        self.assertEqual(name_parts["middle_name"], "Q.")
        self.assertEqual(name_parts["last_name"], "Doe")

        # Complex name with multiple middle parts
        name_parts = self.mapper._parse_author_name("Monica C. Munoz-Torres")
        self.assertEqual(name_parts["first_name"], "Monica")
        self.assertEqual(name_parts["middle_name"], "C.")
        self.assertEqual(name_parts["last_name"], "Munoz-Torres")

        # Last, First format
        name_parts = self.mapper._parse_author_name("Doe, John Q.")
        self.assertEqual(name_parts["first_name"], "John")
        self.assertEqual(name_parts["middle_name"], "Q.")
        self.assertEqual(name_parts["last_name"], "Doe")

        # Single name
        name_parts = self.mapper._parse_author_name("Madonna")
        self.assertEqual(name_parts["first_name"], "")
        self.assertEqual(name_parts["middle_name"], "")
        self.assertEqual(name_parts["last_name"], "Madonna")

    def test_extract_authors(self):
        """Test author extraction."""
        authors_data = [
            {"name": "John Doe"},
            {"name": "Jane Smith", "affiliation": "MIT"},
            {"name": ""},  # Empty name
        ]

        authors = self.mapper._extract_authors(authors_data)

        self.assertEqual(len(authors), 2)  # Empty name should be skipped

        # First author
        self.assertEqual(authors[0]["full_name"], "John Doe")
        self.assertEqual(authors[0]["first_name"], "John")
        self.assertEqual(authors[0]["last_name"], "Doe")
        self.assertNotIn("affiliations", authors[0])

        # Second author with affiliation
        self.assertEqual(authors[1]["full_name"], "Jane Smith")
        self.assertEqual(authors[1]["first_name"], "Jane")
        self.assertEqual(authors[1]["last_name"], "Smith")
        self.assertEqual(authors[1]["affiliations"], ["MIT"])

    def test_map_batch(self):
        """Test batch mapping of records."""
        records = [
            self.sample_record,
            {  # Invalid record - missing required fields
                "id": "invalid",
                "title": "Invalid Paper",
            },
        ]

        with patch.object(self.mapper, "map_to_paper") as mock_map:
            mock_paper = MagicMock(spec=Paper)
            mock_map.return_value = mock_paper

            results = self.mapper.map_batch(records, validate=True)

            # Should only map the valid record
            self.assertEqual(len(results), 1)
            mock_map.assert_called_once()

    def test_parse_xml_entry_with_comment(self):
        """Test XML entry parsing with comment field."""
        parsed = self.mapper._parse_xml_entry(self.sample_xml_with_extras)

        # Check basic fields (second entry from fixture)
        self.assertEqual(
            parsed["id"], "http://arxiv.org/abs/2509.08817v1"  # NOSONAR - Ignore http
        )
        self.assertEqual(
            parsed["title"],
            "QCardEst/QCardCorr: Quantum Cardinality Estimation and Correction",
        )

        # Check comment field
        self.assertEqual(parsed["comment"], "7 pages")

        # Check authors
        self.assertEqual(len(parsed["authors"]), 3)
        self.assertEqual(parsed["authors"][0]["name"], "Tobias Winker")

    def test_empty_response_handling(self):
        """Test handling of empty ArXiv response."""
        # Parse the empty response to see there are no entries
        root = ET.fromstring(self.empty_response_xml)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")

        # Should have no entries
        self.assertEqual(len(entries), 0)

    def test_urls_without_links(self):
        """Test URL construction when links are not provided."""
        # XML without link elements
        xml_no_links = """<entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/2509.10432v1</id>
    <title>Test Paper</title>
    <summary>Test summary</summary>
    <published>2025-09-12T17:38:46Z</published>
    <author><name>Test Author</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""

        record = {"raw_xml": xml_no_links}
        paper = self.mapper.map_to_paper(record)

        # Should construct URLs from ArXiv ID
        self.assertEqual(paper.url, "https://arxiv.org/abs/2509.10432v1")
        self.assertEqual(
            paper.pdf_url,
            "https://arxiv.org/pdf/2509.10432v1.pdf",
        )

    def test_map_to_hubs(self):
        """
        Test map_to_hubs returns expected hubs including arxiv hub.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        cs_hub, _ = Hub.objects.get_or_create(
            slug="computer-science",
            defaults={"name": "Computer Science"},
        )
        mock_hub_mapper.map.return_value = [cs_hub]

        mapper = ArXivMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        # Should be called once for primary category
        mock_hub_mapper.map.assert_called_once_with("cs.CL", "arxiv")
        self.assertEqual(len(hubs), 2)
        self.assertIn(cs_hub, hubs)
        self.assertIn(self.arxiv_hub, hubs)

    def test_map_to_hubs_without_hub_mapper(self):
        """
        Test map_to_hubs falls back to default behavior without hub_mapper,
        i.e., only returning the journal hub.
        """
        # Arrange
        mapper = ArXivMapper(None)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.arxiv_hub)

    def test_map_to_hubs_no_duplicate_arxiv_hub(self):
        """
        Test that arxiv hub is not duplicated if already returned by hub_mapper.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        cs_hub, _ = Hub.objects.get_or_create(
            slug="computer-science",
            defaults={"name": "Computer Science"},
        )
        # hub_mapper returns both hubs including the arxiv hub
        mock_hub_mapper.map.return_value = [cs_hub, self.arxiv_hub]

        mapper = ArXivMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        # Should only have 2 hubs, not duplicate the arxiv hub
        self.assertEqual(len(hubs), 2)
        self.assertEqual(hubs.count(self.arxiv_hub), 1)  # Only appears once
        self.assertIn(cs_hub, hubs)
        self.assertIn(self.arxiv_hub, hubs)

    def test_map_to_hubs_without_primary_category(self):
        """
        Test map_to_hubs with record that has no primary_category field.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        mapper = ArXivMapper(mock_hub_mapper)

        # XML without primary_category
        xml_no_primary = """<entry xmlns="http://www.w3.org/2005/Atom">
    <id>http://arxiv.org/abs/2509.10432v1</id>
    <title>Test Paper</title>
    <summary>Test summary</summary>
    <published>2025-09-12T17:38:46Z</published>
    <author><name>Test Author</name></author>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>"""

        record_no_primary = {"raw_xml": xml_no_primary}
        paper = mapper.map_to_paper(record_no_primary)

        # Act
        hubs = mapper.map_to_hubs(record_no_primary)

        # Assert
        mock_hub_mapper.map.assert_not_called()
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.arxiv_hub)

    def test_map_to_hubs_hub_mapper_returns_empty(self):
        """
        Test map_to_hubs when hub_mapper returns empty list.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        mock_hub_mapper.map.return_value = []

        mapper = ArXivMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        mock_hub_mapper.map.assert_called_once_with("cs.CL", "arxiv")
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.arxiv_hub)
