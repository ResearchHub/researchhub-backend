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
        self.mock_openalex_mapper = Mock()
        self.service = PaperOpenAlexEnrichmentService(
            self.mock_openalex_client, self.mock_openalex_mapper
        )

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
                "authorships": [],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper with no license data
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = None
        mock_mapped_paper.pdf_url = None
        mock_mapped_paper.pdf_license_url = None
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

        result = self.service.enrich_paper_with_openalex(self.paper)

        # Now returns success even without license (authors/institutions can still be processed)
        self.assertEqual(result.status, "success")

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
                "authorships": [],  # No authors for this test
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper with all license data
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = (
            "https://creativecommons.org/licenses/by/4.0"
        )
        mock_mapped_paper.pdf_url = "https://arxiv.org/pdf/2301.00001.pdf"
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

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

    def test_enrich_paper_incomplete_data_pdf_url_only(self):
        """Test enrichment succeeds but skips license when only PDF URL is available."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                },
                "authorships": [],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper with only pdf_url
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = None
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.pdf_url = "https://arxiv.org/pdf/2301.00001.pdf"
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

        result = self.service.enrich_paper_with_openalex(self.paper)

        # Now returns success (can still process authors/institutions)
        self.assertEqual(result.status, "success")

    def test_enrich_paper_incomplete_data_license_only(self):
        """Test enrichment succeeds but skips license when only license is available."""
        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "license": "cc-by-sa",
                },
                "authorships": [],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper with only license
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = "cc-by-sa"
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.pdf_url = None
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

        result = self.service.enrich_paper_with_openalex(self.paper)

        # Now returns success (can still process authors/institutions)
        self.assertEqual(result.status, "success")

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
                    "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                },
                "authorships": [],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper with complete license data
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = (
            "https://creativecommons.org/licenses/by/4.0"
        )
        mock_mapped_paper.pdf_url = "https://arxiv.org/pdf/2301.00001.pdf"
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

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
                        "primary_location": {
                            "license": "cc-by",
                            "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                        },
                        "authorships": [],
                    }
                }
            else:
                return None  # Not found

        self.mock_openalex_client.fetch_by_doi.side_effect = mock_fetch

        # Mock the mapped paper with complete license data
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.pdf_url = "https://arxiv.org/pdf/2301.00001.pdf"
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

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

    def test_enrich_paper_already_has_data(self):
        """Test enrichment skips license update but still processes authors when paper already has license data."""
        # Set up paper with existing license data
        self.paper.pdf_license = "existing-license"
        self.paper.pdf_url = "https://existing.com/pdf.pdf"
        self.paper.save()

        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {
                    "license": "cc-by",
                    "pdf_url": "https://arxiv.org/pdf/2301.00001.pdf",
                },
                "authorships": [],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = "cc-by"
        mock_mapped_paper.pdf_license_url = None
        mock_mapped_paper.pdf_url = "https://arxiv.org/pdf/2301.00001.pdf"
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock mapper methods for authors/institutions/authorships
        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

        result = self.service.enrich_paper_with_openalex(self.paper)

        # Now returns success (still processes authors/institutions)
        self.assertEqual(result.status, "success")

        # Verify existing license data wasn't changed
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.pdf_license, "existing-license")
        self.assertEqual(self.paper.pdf_url, "https://existing.com/pdf.pdf")

    def test_enrich_paper_with_authors_and_institutions(self):
        """Test enrichment with authors and institutions."""
        from institution.models import Institution
        from paper.related_models.authorship_model import Authorship
        from user.related_models.author_model import Author

        openalex_data = {
            "raw_data": {
                "id": "https://openalex.org/W123456",
                "title": "Test Paper",
                "primary_location": {},  # No license data
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A123456",
                            "display_name": "John Doe",
                            "orcid": "https://orcid.org/0000-0001-2345-6789",
                        },
                        "raw_author_name": "John Doe",
                        "author_position": "first",
                        "is_corresponding": True,
                        "institutions": [
                            {
                                "id": "https://openalex.org/I123456",
                                "display_name": "Test University",
                                "ror": "https://ror.org/abc123",
                                "country_code": "US",
                            }
                        ],
                    }
                ],
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper (no license)
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = None
        mock_mapped_paper.pdf_url = None
        mock_mapped_paper.pdf_license_url = None
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        # Mock the mapper methods
        mock_author = Mock(spec=Author)
        mock_author.orcid_id = "0000-0001-2345-6789"
        mock_author.openalex_ids = ["A123456"]
        mock_author.first_name = "John"
        mock_author.last_name = "Doe"
        mock_author.created_source = Author.SOURCE_OPENALEX
        mock_author.save = Mock()

        mock_institution = Mock(spec=Institution)
        mock_institution.ror_id = "abc123"
        mock_institution.display_name = "Test University"
        mock_institution.country_code = "US"

        mock_authorship = Mock(spec=Authorship)
        mock_authorship.paper = self.paper
        mock_authorship.author_position = "first"
        mock_authorship.raw_author_name = "John Doe"
        mock_authorship.is_corresponding = True
        mock_authorship._orcid_id = "0000-0001-2345-6789"
        mock_authorship._institution_ror_ids = ["abc123"]
        mock_authorship.save = Mock()
        mock_authorship.institutions = Mock()

        self.mock_openalex_mapper.map_to_authors.return_value = [mock_author]
        self.mock_openalex_mapper.map_to_institutions.return_value = [mock_institution]
        self.mock_openalex_mapper.map_to_authorships.return_value = [mock_authorship]

        result = self.service.enrich_paper_with_openalex(self.paper)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.authors_created, 1)
        self.assertEqual(result.authors_updated, 0)
        # Institutions created will be 0 since we skip creation without full data
        self.assertEqual(result.institutions_created, 0)

    def test_process_authors_creates_new_author(self):
        """Test that process_authors creates new authors."""
        from user.related_models.author_model import Author

        openalex_data = {
            "raw_data": {
                "authorships": [
                    {
                        "author": {
                            "id": "https://openalex.org/A123456",
                            "display_name": "Jane Smith",
                            "orcid": "https://orcid.org/0000-0002-3456-7890",
                        }
                    }
                ]
            }
        }

        # Mock mapper to return a new author instance
        mock_author = Mock(spec=Author)
        mock_author.orcid_id = "0000-0002-3456-7890"
        mock_author.openalex_ids = ["A123456"]
        mock_author.first_name = "Jane"
        mock_author.last_name = "Smith"
        mock_author.created_source = Author.SOURCE_OPENALEX

        self.mock_openalex_mapper.map_to_authors.return_value = [mock_author]

        authors_created, authors_updated = self.service.process_authors(
            self.paper, openalex_data
        )

        self.assertEqual(authors_created, 1)
        self.assertEqual(authors_updated, 0)

        # Verify the author was created in the database
        author = Author.objects.get(orcid_id="0000-0002-3456-7890")
        self.assertEqual(author.first_name, "Jane")
        self.assertEqual(author.last_name, "Smith")
        self.assertEqual(author.openalex_ids, ["A123456"])

    def test_batch_enrichment_with_authors(self):
        """Test batch enrichment always includes authors and institutions."""
        paper = create_paper(title="Paper")
        paper.doi = "10.1234/test"
        paper.save()

        openalex_data = {
            "raw_data": {
                "authorships": [],
                "primary_location": {},
            }
        }
        self.mock_openalex_client.fetch_by_doi.return_value = openalex_data

        # Mock the mapped paper
        mock_mapped_paper = Mock()
        mock_mapped_paper.pdf_license = None
        mock_mapped_paper.pdf_url = None
        mock_mapped_paper.pdf_license_url = None
        self.mock_openalex_mapper.map_to_paper.return_value = mock_mapped_paper

        self.mock_openalex_mapper.map_to_authors.return_value = []
        self.mock_openalex_mapper.map_to_institutions.return_value = []
        self.mock_openalex_mapper.map_to_authorships.return_value = []

        result = self.service.enrich_papers_batch([paper.id])

        self.assertEqual(result.total, 1)
        self.assertEqual(result.success_count, 1)
        self.assertEqual(result.total_authors_created, 0)
        self.assertEqual(result.total_authors_updated, 0)
        self.assertEqual(result.total_institutions_created, 0)
        self.assertEqual(result.total_institutions_updated, 0)
        self.assertEqual(result.total_authorships_created, 0)
