from django.test import SimpleTestCase

from paper.ingestion.mappers.enrichment.openalex import OpenAlexMapper


class OpenAlexMapperLicenseExtractionTests(SimpleTestCase):
    """Tests for _extract_license_info handling of null/missing source data."""

    def setUp(self):
        self.mapper = OpenAlexMapper()

    def test_extract_license_info_with_null_source(self):
        """
        Regression test for RESEARCHHUB-BACKEND-4KPZ:
        When primary_location.source is explicitly None (not missing),
        dict.get("source", {}) returns None rather than {},
        causing AttributeError on .get("display_name").
        """
        record = {
            "primary_location": {
                "license": "cc-by",
                "license_id": "https://creativecommons.org/licenses/by/4.0/",
                "pdf_url": "https://example.com/paper.pdf",
                "landing_page_url": "https://doi.org/10.1234/test",
                "source": None,
            }
        }
        result = self.mapper._extract_license_info(record)

        self.assertEqual(result["license"], "cc-by")
        self.assertEqual(result["pdf_url"], "https://example.com/paper.pdf")
        self.assertIsNone(result["journal_name"])

    def test_extract_license_info_with_missing_source(self):
        """Source key completely absent from primary_location."""
        record = {
            "primary_location": {
                "license": "cc-by",
                "pdf_url": "https://example.com/paper.pdf",
                "landing_page_url": "https://doi.org/10.1234/test",
            }
        }
        result = self.mapper._extract_license_info(record)

        self.assertEqual(result["license"], "cc-by")
        self.assertIsNone(result["journal_name"])

    def test_extract_license_info_with_valid_source(self):
        """Normal case: source is a dict with display_name."""
        record = {
            "primary_location": {
                "license": "cc-by",
                "pdf_url": "https://example.com/paper.pdf",
                "landing_page_url": "https://doi.org/10.1234/test",
                "source": {
                    "display_name": "Nature",
                    "type": "journal",
                },
            }
        }
        result = self.mapper._extract_license_info(record)

        self.assertEqual(result["journal_name"], "Nature")

    def test_extract_license_info_with_empty_primary_location(self):
        """primary_location is an empty dict."""
        record = {"primary_location": {}}
        result = self.mapper._extract_license_info(record)

        self.assertIsNone(result["license"])
        self.assertIsNone(result["pdf_url"])

    def test_extract_license_info_with_null_primary_location(self):
        """primary_location is None."""
        record = {"primary_location": None}
        result = self.mapper._extract_license_info(record)

        self.assertIsNone(result["license"])
        self.assertIsNone(result["pdf_url"])

    def test_extract_license_info_source_is_string(self):
        """Source is a non-dict value (string) - should not crash."""
        record = {
            "primary_location": {
                "license": "cc-by",
                "source": "some-string-value",
            }
        }
        result = self.mapper._extract_license_info(record)
        self.assertIsNone(result["journal_name"])
