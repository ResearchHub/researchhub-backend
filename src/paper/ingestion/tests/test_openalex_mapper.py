from unittest import TestCase

from paper.ingestion.mappers.enrichment.openalex import OpenAlexMapper


class TestExtractLicenseInfo(TestCase):
    """Tests for _extract_license_info handling of null/missing source fields."""

    def setUp(self):
        self.mapper = OpenAlexMapper()

    def test_source_is_none(self):
        record = {
            "primary_location": {
                "license": "cc-by",
                "source": None,
            }
        }
        result = self.mapper._extract_license_info(record)
        self.assertEqual(result["license"], "cc-by")
        self.assertIsNone(result["journal_name"])

    def test_source_is_valid_dict(self):
        record = {
            "primary_location": {
                "license": "cc-by",
                "source": {"display_name": "Nature"},
            }
        }
        result = self.mapper._extract_license_info(record)
        self.assertEqual(result["journal_name"], "Nature")

    def test_source_missing_from_location(self):
        record = {
            "primary_location": {
                "license": "cc-by",
            }
        }
        result = self.mapper._extract_license_info(record)
        self.assertIsNone(result["journal_name"])

    def test_primary_location_is_none(self):
        record = {"primary_location": None}
        result = self.mapper._extract_license_info(record)
        self.assertIsNone(result["license"])
        self.assertIsNone(result.get("journal_name"))

    def test_primary_location_missing(self):
        record = {}
        result = self.mapper._extract_license_info(record)
        self.assertIsNone(result["license"])

    def test_source_is_non_dict(self):
        record = {
            "primary_location": {
                "license": "cc-by",
                "source": "not a dict",
            }
        }
        result = self.mapper._extract_license_info(record)
        self.assertIsNone(result["journal_name"])
