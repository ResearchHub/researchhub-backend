"""
Tests for the OpenAlex enrichment service.
"""

from unittest.mock import Mock

from django.test import TestCase

from paper.ingestion.services.openalex_enrichment import PaperOpenAlexEnrichmentService
from paper.tests.helpers import create_paper


class TestPaperOpenAlexEnrichmentService(TestCase):
    """Test cases for PaperOpenAlexEnrichmentService."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_openalex_client = Mock()
        self.service = PaperOpenAlexEnrichmentService(self.mock_openalex_client)

        # Create test paper with DOI
        self.paper = create_paper(title="Test Paper")
        self.paper.doi = "10.1234/test.2024"
        self.paper.save()

    def test_get_recent_papers_with_dois(self):
        """Test getting recent papers with DOIs."""
        # Create papers with and without DOIs
        paper_with_doi = create_paper(title="Paper with DOI")
        paper_with_doi.doi = "10.1234/test1"
        paper_with_doi.save()

        paper_without_doi = create_paper(title="Paper without DOI")

        # Query recent papers
        paper_ids = self.service.get_recent_papers_with_dois(days=7)

        # Should include papers with DOIs
        self.assertIn(paper_with_doi.id, paper_ids)
        self.assertIn(self.paper.id, paper_ids)

        # Should not include papers without DOIs
        self.assertNotIn(paper_without_doi.id, paper_ids)

    def test_enrich_paper_no_doi(self):
        """Test enriching a paper without a DOI."""
        paper_no_doi = create_paper(title="No DOI Paper")
        result = self.service.enrich_paper_with_openalex(paper_no_doi)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "no_doi")
        self.mock_openalex_client.fetch_by_doi.assert_not_called()

    def test_enrich_paper_not_found_in_openalex(self):
        """Test enriching a paper not found in OpenAlex."""
        self.mock_openalex_client.fetch_by_doi.return_value = None

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_openalex_data")
        self.mock_openalex_client.fetch_by_doi.assert_called_once_with(self.paper.doi)

    def test_enrich_paper_no_license_in_openalex(self):
        """Test enriching a paper with no license information in OpenAlex."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {},
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "not_found")
        self.assertEqual(result.reason, "no_license_in_openalex")

    def test_enrich_paper_success_with_primary_location_full(self):
        """Test successful enrichment with all fields from primary_location."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "license": "cc-by",
                    "license_id": "https://creativecommons.org/licenses/by/4.0",
                    "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                },
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.license, "cc-by")
        self.assertEqual(
            result.license_url, "https://creativecommons.org/licenses/by/4.0"
        )

        # Verify paper was updated with all fields
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_license, "cc-by")
        self.assertEqual(
            self.paper.pdf_license_url, "https://creativecommons.org/licenses/by/4.0"
        )
        self.assertEqual(self.paper.pdf_url, "https://arxiv.org/pdf/2301.00001.pdf")

    def test_enrich_paper_success_with_pdf_url_only(self):
        """Test successful enrichment with only PDF URL from primary_location."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                },
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "success")

        # Verify paper was updated with PDF URL
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_url, "https://arxiv.org/pdf/2301.00001.pdf")

    def test_enrich_paper_success_with_license_only(self):
        """Test successful enrichment with only license from primary_location."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "license": "cc-by-sa",
                },
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.license, "cc-by-sa")
        self.assertIsNone(result.license_url)

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_license, "cc-by-sa")

    def test_enrich_paper_success_only_license_url(self):
        """Test successful enrichment with only license URL."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "license_id": "https://creativecommons.org/licenses/by/4.0",
                },
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "success")
        self.assertIsNone(result.license)
        self.assertEqual(
            result.license_url, "https://creativecommons.org/licenses/by/4.0"
        )

        # Verify paper was updated
        self.paper.refresh_from_db()
        self.assertEqual(
            self.paper.pdf_license_url, "https://creativecommons.org/licenses/by/4.0"
        )

    def test_enrich_paper_error_handling(self):
        """Test error handling during enrichment."""
        self.mock_openalex_client.fetch_by_doi.side_effect = Exception(
            "API connection error"
        )

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "error")
        self.assertIn("API connection error", result.reason)

    def test_enrich_papers_batch_success(self):
        """Test batch enrichment with successful papers."""
        paper1 = create_paper(title="Paper 1")
        paper1.doi = "10.1234/test1"
        paper1.save()

        paper2 = create_paper(title="Paper 2")
        paper2.doi = "10.1234/test2"
        paper2.save()

        openalex_data = {
            "raw_data": {
                "primary_location": {
                    "license": "cc-by",
                    "license_id": "https://creativecommons.org/licenses/by/4.0",
                },
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        result = self.service.enrich_papers_batch([paper1.id, paper2.id])

        self.assertEqual(result.total, 2)
        self.assertEqual(result.success_count, 2)
        self.assertEqual(result.not_found_count, 0)
        self.assertEqual(result.error_count, 0)

    def test_enrich_papers_batch_mixed_results(self):
        """Test batch enrichment with mixed results."""
        paper1 = create_paper(title="Paper 1")
        paper1.doi = "10.1234/test1"
        paper1.save()

        paper2 = create_paper(title="Paper 2")  # No DOI - will be skipped

        paper3 = create_paper(title="Paper 3")
        paper3.doi = "10.1234/test3"
        paper3.save()

        def mock_fetch(doi):
            if doi == "10.1234/test1":
                return {
                    "raw_data": {
                        "primary_location": {"license": "cc-by"},
                    }
                }
            else:
                return None  # Not found

        self.mock_openalex_client.fetch_by_doi.side_effect = mock_fetch

        result = self.service.enrich_papers_batch([paper1.id, paper2.id, paper3.id])

        self.assertEqual(result.total, 3)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.not_found_count, 2)  # paper2 skipped, paper3 not found
        self.assertEqual(result.error_count, 0)

    def test_enrich_papers_batch_paper_not_exists(self):
        """Test batch enrichment with non-existent paper ID."""
        non_existent_id = 999999
        result = self.service.enrich_papers_batch([non_existent_id])

        self.assertEqual(result.total, 1)
        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.not_found_count, 0)
        self.assertEqual(result.error_count, 1)

    def test_enrich_papers_batch_unexpected_error(self):
        """Test batch enrichment with unexpected errors."""
        paper = create_paper(title="Paper")
        paper.doi = "10.1234/test"
        paper.save()

        self.mock_openalex_client.fetch_by_doi.side_effect = Exception(
            "Unexpected error"
        )

        result = self.service.enrich_papers_batch([paper.id])

        self.assertEqual(result.total, 1)
        self.assertEqual(result.success_count, 0)
        self.assertEqual(result.not_found_count, 0)
        self.assertEqual(result.error_count, 1)

    def test_extract_license_info_from_primary_location(self):
        """Test that license extraction uses primary_location."""
        raw_data = {
            "primary_location": {
                "license": "cc-by",
                "license_id": "https://creativecommons.org/licenses/by/4.0",
                "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
            },
        }

        license_info = self.service._extract_license_info(raw_data)

        self.assertEqual(license_info["license"], "cc-by")
        self.assertEqual(
            license_info["license_url"],
            "https://creativecommons.org/licenses/by/4.0",
        )
        self.assertEqual(
            license_info["pdf_url"], "https://arxiv.org/pdf/2301.00001.pdf"
        )

    def test_extract_license_info_empty_primary_location(self):
        """Test that extraction returns None values when primary_location is empty."""
        raw_data = {
            "primary_location": {},
        }

        license_info = self.service._extract_license_info(raw_data)

        self.assertIsNone(license_info["license"])
        self.assertIsNone(license_info["license_url"])
        self.assertIsNone(license_info["pdf_url"])

    def test_update_paper_license_all_fields(self):
        """Test updating all license and PDF fields."""
        license_info = {
            "license": "cc-by",
            "license_url": "https://creativecommons.org/licenses/by/4.0",
            "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
        }

        self.service._update_paper_license(self.paper, license_info)

        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_license, "cc-by")
        self.assertEqual(
            self.paper.pdf_license_url, "https://creativecommons.org/licenses/by/4.0"
        )
        self.assertEqual(self.paper.pdf_url, "https://arxiv.org/pdf/2301.00001.pdf")

    def test_update_paper_license_only_license(self):
        """Test updating only license field."""
        license_info = {"license": "cc-by-nc", "license_url": None, "pdf_url": None}

        self.service._update_paper_license(self.paper, license_info)

        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_license, "cc-by-nc")

    def test_update_paper_license_only_url(self):
        """Test updating only license URL field."""
        license_info = {
            "license": None,
            "license_url": "https://creativecommons.org/licenses/by/4.0",
            "pdf_url": None,
        }

        self.service._update_paper_license(self.paper, license_info)

        self.paper.refresh_from_db()
        self.assertEqual(
            self.paper.pdf_license_url, "https://creativecommons.org/licenses/by/4.0"
        )

    def test_update_paper_pdf_url_only(self):
        """Test updating only PDF URL field."""
        license_info = {
            "license": None,
            "license_url": None,
            "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
        }

        self.service._update_paper_license(self.paper, license_info)

        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_url, "https://arxiv.org/pdf/2301.00001.pdf")
