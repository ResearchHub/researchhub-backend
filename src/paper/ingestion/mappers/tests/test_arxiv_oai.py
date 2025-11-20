"""
Tests for ArXiv OAI mapper.
"""

import os
from unittest.mock import MagicMock, patch

from django.test import TestCase

from hub.models import Hub
from paper.ingestion.mappers.arxiv_oai import ArXivOAIMapper
from paper.models import Paper


class TestArXivOAIMapper(TestCase):

    def setUp(self):
        self.mapper = ArXivOAIMapper(None)

        self.arxiv_hub, _ = Hub.objects.get_or_create(
            slug="arxiv",
            defaults={
                "name": "ArXiv",
                "namespace": Hub.Namespace.JOURNAL,
            },
        )

        # Load fixture files
        fixtures_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "clients",
            "preprints",
            "tests",
            "fixtures",
        )

        # Read the sample metadata XML
        with open(
            os.path.join(fixtures_dir, "arxiv_oai_metadata_sample.xml"), "r"
        ) as f:
            self.sample_metadata_xml = f.read()

        # Create parsed records for testing
        self.sample_record = {"raw_xml": self.sample_metadata_xml}

    def test_validate_valid_record(self):
        """
        Test validation of a valid ArXiv OAI record.
        """
        # Act
        result = self.mapper.validate(self.sample_record)

        # Assert
        self.assertTrue(result)

    def test_validate_missing_required_fields(self):
        """
        Test validation fails for missing required fields.
        """
        # Arrange
        missing_id_xml = """<metadata xmlns="http://www.openarchives.org/OAI/2.0/">
    <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
      <title>Test Paper</title>
      <authors><author><keyname>Doe</keyname><forenames>John</forenames></author></authors>
    </arXiv>
  </metadata>"""
        record = {"raw_xml": missing_id_xml}

        # Act
        result = self.mapper.validate(record)

        # Assert
        self.assertFalse(result)

    def test_validate_missing_dates(self):
        """
        Test validation fails when no dates are present.
        """
        # Arrange
        missing_dates_xml = """<metadata xmlns="http://www.openarchives.org/OAI/2.0/">
    <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
      <id>2507.00004</id>
      <title>Test Paper</title>
      <authors><author><keyname>Doe</keyname><forenames>John</forenames></author></authors>
    </arXiv>
  </metadata>"""
        record = {"raw_xml": missing_dates_xml}

        # Act
        result = self.mapper.validate(record)

        # Assert
        self.assertFalse(result)

    def test_map_to_paper(self):
        """
        Test mapping ArXiv OAI record to Paper model.
        """
        # Act
        paper = self.mapper.map_to_paper(self.sample_record)

        # Assert
        # Check basic fields
        self.assertEqual(paper.doi, "10.48550/arXiv.2507.00004")
        self.assertEqual(paper.external_source, "arxiv")
        self.assertEqual(
            paper.title,
            "A Theory of Inference Compute Scaling: Reasoning through "
            "Directed Stochastic Skill Search",
        )
        self.assertIn("Large language models", paper.abstract)

        # Check dates (should use created over updated)
        self.assertEqual(paper.paper_publish_date, "2025-07-10")

        # Check authors
        self.assertEqual(len(paper.raw_authors), 3)
        self.assertEqual(paper.raw_authors[0]["full_name"], "Austin R. Ellis-Mohr")
        self.assertEqual(paper.raw_authors[0]["first_name"], "Austin R.")
        self.assertEqual(paper.raw_authors[0]["last_name"], "Ellis-Mohr")
        self.assertEqual(paper.raw_authors[2]["full_name"], "Lav R. Varshney")
        self.assertEqual(paper.raw_authors[2]["first_name"], "Lav R.")
        self.assertEqual(paper.raw_authors[2]["last_name"], "Varshney")

        # Check open access
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")

        # Check license
        self.assertEqual(paper.pdf_license, "cc-by-4.0")
        self.assertEqual(
            paper.pdf_license_url,
            "http://creativecommons.org/licenses/by/4.0/",  # NOSONAR - http
        )

        # Check URLs
        self.assertEqual(paper.pdf_url, "https://arxiv.org/pdf/2507.00004.pdf")
        self.assertEqual(paper.url, "https://arxiv.org/abs/2507.00004")

        # Check external metadata
        self.assertEqual(paper.external_metadata["external_id"], "2507.00004")

        # Check flags
        self.assertTrue(paper.retrieved_from_external_source)

    def test_parse_xml_metadata(self):
        """
        Test XML metadata parsing.
        """
        # Act
        parsed = self.mapper._parse_xml_metadata(self.sample_metadata_xml)

        # Assert
        # Check basic fields
        self.assertEqual(parsed["id"], "2507.00004")
        self.assertEqual(
            parsed["title"],
            "A Theory of Inference Compute Scaling: Reasoning through "
            "Directed Stochastic Skill Search",
        )
        self.assertIn("Large language models", parsed["abstract"])
        self.assertEqual(parsed["created"], "2025-07-10")
        self.assertEqual(parsed["updated"], "2025-07-11")

        # Check authors
        self.assertEqual(len(parsed["authors"]), 3)
        self.assertEqual(parsed["authors"][0]["name"], "Austin R. Ellis-Mohr")
        self.assertEqual(parsed["authors"][0]["keyname"], "Ellis-Mohr")
        self.assertEqual(parsed["authors"][0]["forenames"], "Austin R.")
        self.assertEqual(parsed["authors"][2]["name"], "Lav R. Varshney")

        # Check categories
        self.assertEqual(parsed["categories"], ["cs.LG", "cs.AI", "cs.CY", "cs.PF"])
        self.assertEqual(parsed["primary_category"], "cs.LG")

        # Check links
        self.assertEqual(
            parsed["links"]["alternate"],
            "https://arxiv.org/abs/2507.00004",
        )
        self.assertEqual(
            parsed["links"]["pdf"],
            "https://arxiv.org/pdf/2507.00004.pdf",
        )

    def test_format_arxiv_doi(self):
        """
        Test ArXiv DOI formatting.
        """
        test_cases = [
            ("without_version", "2507.00004", "10.48550/arXiv.2507.00004"),
            ("with_version", "2507.00004v1", "10.48550/arXiv.2507.00004"),
            ("empty_string", "", ""),
            ("none_value", None, ""),
        ]

        for name, given, expected in test_cases:
            with self.subTest(name=name):
                # Act
                actual = self.mapper._format_arxiv_doi(given)
                # Assert
                self.assertEqual(actual, expected)

    def test_parse_date(self):
        """
        Test date parsing from OAI format.
        """
        test_cases = [
            ("simple_date", "2025-07-10", "2025-07-10"),
            ("iso_date", "2025-07-10T17:38:46Z", "2025-07-10"),
            ("invalid_date", "invalid-date", None),
            ("none_date", None, None),
        ]

        for name, given, expected in test_cases:
            with self.subTest(name=name):
                # Act
                actual = self.mapper._parse_date(given)
                # Assert
                self.assertEqual(actual, expected)

    def test_get_best_date(self):
        """
        Test getting the best available date.
        """
        test_cases = [
            (
                "both_dates",
                {
                    "created": "2025-07-10",
                    "updated": "2025-07-11",
                },
                "2025-07-10",
            ),
            (
                "only_created",
                {"created": "2025-07-10"},
                "2025-07-10",
            ),
            (
                "only_updated",
                {"updated": "2025-07-11"},
                "2025-07-11",
            ),
            (
                "no_dates",
                {},
                None,
            ),
        ]

        for name, given, expected in test_cases:
            with self.subTest(name=name):
                # Act
                actual = self.mapper._get_best_date(given)
                # Assert
                self.assertEqual(actual, expected)

    def test_parse_author_name(self):
        test_cases = [
            (
                "simple_name",
                "John Doe",
                {"first_name": "John", "middle_name": "", "last_name": "Doe"},
            ),
            (
                "three_part_name",
                "John Q. Doe",
                {"first_name": "John", "middle_name": "Q.", "last_name": "Doe"},
            ),
            (
                "single_name",
                "Madonna",
                {"first_name": "", "middle_name": "", "last_name": "Madonna"},
            ),
        ]

        for name, given, expected in test_cases:
            with self.subTest(name=name):
                # Act
                actual = self.mapper._parse_author_name(given)
                # Assert
                self.assertEqual(actual, expected)

    def test_extract_authors(self):
        """
        Test author extraction from OAI format.
        """
        # Arrange
        authors_data = [
            {
                "name": "John Doe",
                "keyname": "Doe",
                "forenames": "John",
            },
            {
                "name": "Jane Smith",
                "keyname": "Smith",
                "forenames": "Jane",
                "affiliation": "MIT",
            },
            {"name": ""},  # Empty name
        ]

        # Act
        authors = self.mapper._extract_authors(authors_data)

        # Assert
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
        """
        Test batch mapping of records.
        """
        # Arrange
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

            # Act
            results = self.mapper.map_batch(records, validate=True)

            # Assert - Should only map the valid record
            self.assertEqual(len(results), 1)
            mock_map.assert_called_once()

    def test_map_to_hubs(self):
        """
        Test map_to_hubs returns expected hubs including ArXiv preprint hub.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        cs_hub, _ = Hub.objects.get_or_create(
            slug="computer-science",
            defaults={"name": "Computer Science"},
        )
        mock_hub_mapper.map.return_value = [cs_hub]

        mapper = ArXivOAIMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Parse record to get primary category
        parsed = mapper._parse_xml_metadata(self.sample_metadata_xml)
        parsed_record = dict(self.sample_record)
        parsed_record.update(parsed)

        # Act
        hubs = mapper.map_to_hubs(paper, parsed_record)

        # Assert
        # Should be called once for primary category
        mock_hub_mapper.map.assert_called_once_with("cs.LG", "arxiv")
        self.assertEqual(len(hubs), 2)
        self.assertIn(cs_hub, hubs)
        self.assertIn(self.arxiv_hub, hubs)

    def test_map_to_hubs_without_hub_mapper(self):
        """
        Test map_to_hubs falls back to default behavior without hub_mapper.
        """
        # Arrange
        mapper = ArXivOAIMapper(None)
        paper = mapper.map_to_paper(self.sample_record)

        # Parse record to get categories
        parsed = mapper._parse_xml_metadata(self.sample_metadata_xml)
        parsed_record = dict(self.sample_record)
        parsed_record.update(parsed)

        # Act
        hubs = mapper.map_to_hubs(paper, parsed_record)

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

        mapper = ArXivOAIMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Parse record to get categories
        parsed = mapper._parse_xml_metadata(self.sample_metadata_xml)
        parsed_record = dict(self.sample_record)
        parsed_record.update(parsed)

        # Act
        hubs = mapper.map_to_hubs(paper, parsed_record)

        # Assert
        # Should only have 2 hubs, not duplicate the arxiv hub
        self.assertEqual(len(hubs), 2)
        self.assertEqual(hubs.count(self.arxiv_hub), 1)  # Only appears once
        self.assertIn(cs_hub, hubs)
        self.assertIn(self.arxiv_hub, hubs)

    def test_parse_license(self):
        """
        Test parsing various license formats.
        """
        # Arrange
        mapper = ArXivOAIMapper(None)

        # Test cases: (input, expected_output, description)
        test_cases = [
            (
                "CC BY-NC-ND 4.0",
                "http://creativecommons.org/licenses/by-nc-nd/4.0/",  # NOSONAR - http
                "cc-by-nc-nd-4.0",
            ),
            (
                "CC BY 4.0",
                "https://creativecommons.org/licenses/by/4.0/",  # NOSONAR - http
                "cc-by-4.0",
            ),
            (
                "CC BY-SA 3.0",
                "http://creativecommons.org/licenses/by-sa/3.0/",  # NOSONAR - http
                "cc-by-sa-3.0",
            ),
            (
                "arXiv non-exclusive",
                "http://arxiv.org/licenses/nonexclusive-distrib/1.0/",  # NOSONAR - http
                "arxiv-nonexclusive-distrib-1.0",
            ),
            (
                "Public domain URL",
                "http://creativecommons.org/publicdomain/",  # NOSONAR - http
                "cc0-1.0",
            ),
            (
                "CC0 short form",
                "CC0",
                "cc0-1.0",
            ),
            (
                "None",
                None,
                None,
            ),
            (
                "Empty string",
                "",
                None,
            ),
            (
                "Whitespace only",
                "   ",
                None,
            ),
            (
                "Unknown format",
                "Some_Custom_License",
                "some-custom-license",
            ),
        ]

        for name, given, expected in test_cases:
            with self.subTest(license=name):
                # Act
                result = mapper._parse_license(given)

                # Assert
                self.assertEqual(result, expected)

    def test_map_to_hubs_without_primary_category(self):
        """
        Test map_to_hubs with record that has no primary_category field.
        """
        # Arrange
        mock_hub_mapper = MagicMock()
        mapper = ArXivOAIMapper(mock_hub_mapper)

        # XML without categories
        xml_no_category = """<metadata xmlns="http://www.openarchives.org/OAI/2.0/">
    <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
      <id>2507.00004</id>
      <created>2025-07-10</created>
      <title>Test Paper</title>
      <abstract>Test abstract</abstract>
      <authors><author><keyname>Doe</keyname><forenames>John</forenames></author></authors>
    </arXiv>
  </metadata>"""

        record_no_primary = {"raw_xml": xml_no_category}
        paper = mapper.map_to_paper(record_no_primary)

        # Act
        hubs = mapper.map_to_hubs(paper, record_no_primary)

        # Assert
        mock_hub_mapper.map.assert_not_called()
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.arxiv_hub)

    def test_map_to_authors_returns_empty(self):
        """Test that map_to_authors returns empty list (no ORCID IDs)."""
        # Act
        authors = self.mapper.map_to_authors(self.sample_record)

        # Assert
        self.assertEqual(authors, [])

    def test_map_to_institutions_returns_empty(self):
        """Test that map_to_institutions returns empty list (no ROR IDs)."""
        # Act
        institutions = self.mapper.map_to_institutions(self.sample_record)

        # Assert
        self.assertEqual(institutions, [])

    def test_map_to_authorships_returns_empty(self):
        """Test that map_to_authorships returns empty list (no author IDs)."""
        # Arrange
        paper = self.mapper.map_to_paper(self.sample_record)

        # Act
        authorships = self.mapper.map_to_authorships(paper, self.sample_record)

        # Assert
        self.assertEqual(authorships, [])
