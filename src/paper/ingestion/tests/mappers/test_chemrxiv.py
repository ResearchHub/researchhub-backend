"""
Tests for ChemRxiv mapper.
"""

import json
from datetime import datetime
from unittest import TestCase
from unittest.mock import MagicMock, patch

from institution.models import Institution
from paper.ingestion.mappers.chemrxiv import ChemRxivMapper
from paper.models import Paper
from user.related_models.author_institution import AuthorInstitution
from user.related_models.author_model import Author


class TestChemRxivMapper(TestCase):
    """Test ChemRxiv mapper functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = ChemRxivMapper()

        # Sample ChemRxiv API response data
        self.sample_record = {
            "id": "68c17d313e708a764924e728",
            "doi": "10.26434/chemrxiv-2025-81glw",
            "vor": None,
            "title": "Comparison of Theoretical Methods for Predicting Tunneling Rates",
            "abstract": "Hydrogen atom abstraction reactions play a central role in astrochemistry.",
            "contentType": {"id": "5ce663395846762193c9c430", "name": "Working Paper"},
            "categories": [
                {
                    "id": "605c72ef153207001f6470ce",
                    "name": "Theoretical and Computational Chemistry",
                    "description": "Research on Theoretical and Computational Chemistry",
                },
                {
                    "id": "60adf37803f321001cb10530",
                    "name": "Computational Chemistry and Modeling",
                    "description": "Research on Computational Chemistry and Modeling",
                },
            ],
            "subject": {
                "id": "5e68cb1bd1f19d49ce3ac739",
                "name": "Chemistry",
                "description": "Discover early research outputs in Chemistry.",
            },
            "status": "PUBLISHED",
            "statusDate": "2025-09-15T13:35:38.016Z",
            "funders": [
                {
                    "funderId": "",
                    "name": "NKFIH",
                    "grantNumber": "TKP2021-NKTA-64",
                    "url": None,
                    "title": None,
                }
            ],
            "authors": [
                {
                    "orcid": None,
                    "title": "Mr",
                    "firstName": "Dávid",
                    "lastName": "Jelenfi",
                    "institutions": [
                        {
                            "name": "ELTE Eötvös Loránd University",
                            "country": "",
                            "rorId": "",
                        }
                    ],
                },
                {
                    "orcid": "0000-0003-1885-3557",
                    "title": "Prof",
                    "firstName": "Péter G.",
                    "lastName": "Szalay",
                    "institutions": [
                        {
                            "name": "ELTE Eötvös Loránd University",
                            "country": "Hungary",
                            "rorId": "https://ror.org/01s2bdc37",
                        }
                    ],
                },
            ],
            "metrics": [
                {"description": "Abstract Views", "value": 100},
                {"description": "Citations", "value": 5},
                {"description": "Content Downloads", "value": 50},
            ],
            "version": "1",
            "submittedDate": "2025-09-10T14:21:27.633Z",
            "publishedDate": "2025-09-15T13:35:38.016Z",
            "approvedDate": "2025-09-15T13:35:20.496Z",
            "keywords": ["tunneling", "quantum chemistry", "astrochemistry"],
            "hasCompetingInterests": False,
            "competingInterestsDeclaration": None,
            "gainedEthicsApproval": "NOT_RELEVANT",
            "asset": {
                "id": "68c1878c10054254a2a1477b",
                "mimeType": "application/pdf",
                "fileName": "paper.pdf",
                "fileSizeBytes": 1793478,
                "original": {
                    "url": "https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/68c17d313e708a764924e728/original/paper.pdf"
                },
            },
            "license": {
                "id": "5cc9d9bf7d4e0000ac04ef25",
                "name": "CC BY NC ND 4.0",
                "description": "This license will allow Site users to copy and redistribute the Content.",
                "url": "https://creativecommons.org/licenses/by-nc-nd/4.0/",
            },
        }

    def test_validate_valid_record(self):
        """Test validation of a valid ChemRxiv record."""
        self.assertTrue(self.mapper.validate(self.sample_record))

    def test_validate_missing_required_fields(self):
        """Test validation fails for missing required fields."""
        # Missing ID
        record = self.sample_record.copy()
        del record["id"]
        self.assertFalse(self.mapper.validate(record))

        # Missing DOI
        record = self.sample_record.copy()
        del record["doi"]
        self.assertFalse(self.mapper.validate(record))

        # Missing title
        record = self.sample_record.copy()
        del record["title"]
        self.assertFalse(self.mapper.validate(record))

        # Missing authors
        record = self.sample_record.copy()
        del record["authors"]
        self.assertFalse(self.mapper.validate(record))

        # Empty authors list
        record = self.sample_record.copy()
        record["authors"] = []
        self.assertFalse(self.mapper.validate(record))

    def test_validate_missing_dates(self):
        """Test validation fails when no dates are present."""
        record = self.sample_record.copy()
        del record["publishedDate"]
        del record["submittedDate"]
        self.assertFalse(self.mapper.validate(record))

    @patch("paper.models.Paper.save")
    def test_map_to_paper(self, mock_save):
        """Test mapping ChemRxiv record to Paper model."""
        paper = self.mapper.map_to_paper(self.sample_record)

        # Check basic fields
        self.assertEqual(paper.doi, "10.26434/chemrxiv-2025-81glw")
        self.assertEqual(paper.external_source, "chemrxiv")
        self.assertEqual(
            paper.title,
            "Comparison of Theoretical Methods for Predicting Tunneling Rates",
        )
        self.assertEqual(
            paper.abstract,
            "Hydrogen atom abstraction reactions play a central role in astrochemistry.",
        )

        # Check dates
        self.assertEqual(paper.paper_publish_date, "2025-09-15")

        # Check authors
        self.assertEqual(len(paper.raw_authors), 2)
        self.assertEqual(paper.raw_authors[0]["first_name"], "Dávid")
        self.assertEqual(paper.raw_authors[0]["last_name"], "Jelenfi")
        self.assertEqual(paper.raw_authors[1]["first_name"], "Péter G.")
        self.assertEqual(paper.raw_authors[1]["last_name"], "Szalay")
        self.assertEqual(paper.raw_authors[1]["orcid"], "0000-0003-1885-3557")
        self.assertEqual(
            paper.raw_authors[1]["orcid_id"], "0000-0003-1885-3557"
        )  # Check orcid_id

        # Check institutions
        self.assertEqual(len(paper.raw_authors[0]["institutions"]), 1)
        self.assertEqual(
            paper.raw_authors[0]["institutions"][0]["name"],
            "ELTE Eötvös Loránd University",
        )
        self.assertEqual(
            paper.raw_authors[0]["institutions"][0]["display_name"],
            "ELTE Eötvös Loránd University",
        )
        self.assertEqual(paper.raw_authors[0]["institutions"][0]["country"], "")
        self.assertEqual(paper.raw_authors[0]["institutions"][0]["ror_id"], "")

        # Check open access
        self.assertTrue(paper.is_open_access)
        self.assertEqual(paper.oa_status, "gold")

        # Check license
        self.assertEqual(paper.pdf_license, "CC BY NC ND 4.0")

        # Check URLs
        self.assertEqual(
            paper.pdf_url,
            "https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/68c17d313e708a764924e728/original/paper.pdf",
        )
        self.assertEqual(
            paper.url,
            "https://chemrxiv.org/engage/chemrxiv/article-details/68c17d313e708a764924e728",
        )

        # Check external metadata
        self.assertEqual(
            paper.external_metadata["chemrxiv_id"], "68c17d313e708a764924e728"
        )
        self.assertEqual(paper.external_metadata["version"], "1")
        self.assertEqual(paper.external_metadata["status"], "PUBLISHED")
        self.assertIn(
            "Theoretical and Computational Chemistry",
            paper.external_metadata["categories"],
        )
        self.assertEqual(paper.external_metadata["subject"], "Chemistry")
        self.assertEqual(
            paper.external_metadata["keywords"],
            ["tunneling", "quantum chemistry", "astrochemistry"],
        )

        # Check funders
        self.assertEqual(len(paper.external_metadata["funders"]), 1)
        self.assertEqual(paper.external_metadata["funders"][0]["name"], "NKFIH")
        self.assertEqual(
            paper.external_metadata["funders"][0]["grant_number"], "TKP2021-NKTA-64"
        )

        # Check metrics
        self.assertEqual(paper.external_metadata["metrics"]["Abstract Views"], 100)
        self.assertEqual(paper.external_metadata["metrics"]["Citations"], 5)

        # Check flags
        self.assertTrue(paper.retrieved_from_external_source)

    def test_parse_date(self):
        """Test date parsing from ISO format."""
        # Valid ISO date
        date = self.mapper._parse_date("2025-09-15T13:35:38.016Z")
        self.assertEqual(date, "2025-09-15")

        # Another valid ISO date
        date = self.mapper._parse_date("2025-01-01T00:00:00.000Z")
        self.assertEqual(date, "2025-01-01")

        # Invalid date
        date = self.mapper._parse_date("invalid-date")
        self.assertIsNone(date)

        # None date
        date = self.mapper._parse_date(None)
        self.assertIsNone(date)

    def test_get_best_date(self):
        """Test getting the best available date."""
        # All dates present - should use publishedDate
        record = {
            "publishedDate": "2025-09-15T13:35:38.016Z",
            "submittedDate": "2025-09-10T14:21:27.633Z",
            "statusDate": "2025-09-12T10:00:00.000Z",
        }
        date = self.mapper._get_best_date(record)
        self.assertEqual(date, "2025-09-15")

        # No published date - should use submittedDate
        record = {
            "submittedDate": "2025-09-10T14:21:27.633Z",
            "statusDate": "2025-09-12T10:00:00.000Z",
        }
        date = self.mapper._get_best_date(record)
        self.assertEqual(date, "2025-09-10")

        # Only status date
        record = {"statusDate": "2025-09-12T10:00:00.000Z"}
        date = self.mapper._get_best_date(record)
        self.assertEqual(date, "2025-09-12")

    def test_extract_authors(self):
        """Test author extraction."""
        authors_data = [
            {
                "firstName": "John",
                "lastName": "Doe",
                "title": "Dr",
                "orcid": "0000-0000-0000-0001",
                "institutions": [
                    {
                        "name": "MIT",
                        "country": "USA",
                        "rorId": "https://ror.org/042nb2s44",
                    }
                ],
            },
            {"firstName": "Jane", "lastName": "Smith", "institutions": []},
        ]

        authors = self.mapper._extract_authors(authors_data)

        self.assertEqual(len(authors), 2)
        self.assertEqual(authors[0]["full_name"], "John Doe")
        self.assertEqual(authors[0]["first_name"], "John")
        self.assertEqual(authors[0]["last_name"], "Doe")
        self.assertEqual(authors[0]["title"], "Dr")
        self.assertEqual(authors[0]["orcid"], "0000-0000-0000-0001")
        self.assertEqual(
            authors[0]["orcid_id"], "0000-0000-0000-0001"
        )  # Check orcid_id
        self.assertEqual(len(authors[0]["institutions"]), 1)
        self.assertEqual(authors[0]["institutions"][0]["name"], "MIT")
        self.assertEqual(authors[0]["institutions"][0]["display_name"], "MIT")
        self.assertEqual(authors[0]["institutions"][0]["country"], "USA")
        self.assertEqual(authors[0]["institutions"][0]["country_code"], "US")
        self.assertEqual(
            authors[0]["institutions"][0]["ror_id"], "https://ror.org/042nb2s44"
        )
        self.assertEqual(
            authors[0]["institutions"][0]["ror"], "https://ror.org/042nb2s44"
        )

        self.assertEqual(authors[1]["full_name"], "Jane Smith")
        self.assertEqual(len(authors[1]["institutions"]), 0)

    def test_extract_categories(self):
        """Test category extraction."""
        categories = [
            {"name": "Chemistry", "id": "123"},
            {"name": "Physics", "id": "456"},
            {"id": "789"},  # No name
        ]

        result = self.mapper._extract_categories(categories)
        self.assertEqual(result, ["Chemistry", "Physics"])

    def test_extract_funders(self):
        """Test funder extraction."""
        funders = [
            {
                "name": "NSF",
                "grantNumber": "123456",
                "funderId": "10.13039/100000001",
                "url": "https://nsf.gov",
                "title": "Research Grant",
            },
            {"name": "NIH", "grantNumber": "789012"},
        ]

        result = self.mapper._extract_funders(funders)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "NSF")
        self.assertEqual(result[0]["grant_number"], "123456")
        self.assertEqual(result[0]["funder_id"], "10.13039/100000001")
        self.assertEqual(result[0]["url"], "https://nsf.gov")
        self.assertEqual(result[0]["title"], "Research Grant")

        self.assertEqual(result[1]["name"], "NIH")
        self.assertEqual(result[1]["grant_number"], "789012")

    def test_extract_metrics(self):
        """Test metrics extraction."""
        metrics = [
            {"description": "Views", "value": 100},
            {"description": "Downloads", "value": 50},
        ]

        result = self.mapper._extract_metrics(metrics)

        self.assertEqual(result["Views"], 100)
        self.assertEqual(result["Downloads"], 50)

    def test_extract_license(self):
        """Test license extraction."""
        license_obj = {
            "id": "123",
            "name": "CC BY 4.0",
            "description": "Creative Commons",
            "url": "https://creativecommons.org/licenses/by/4.0/",
        }

        result = self.mapper._extract_license(license_obj)
        self.assertEqual(result, "CC BY 4.0")

        # Test with None
        result = self.mapper._extract_license(None)
        self.assertIsNone(result)

    def test_extract_pdf_url(self):
        """Test PDF URL extraction."""
        asset = {"id": "123", "original": {"url": "https://chemrxiv.org/paper.pdf"}}

        result = self.mapper._extract_pdf_url(asset)
        self.assertEqual(result, "https://chemrxiv.org/paper.pdf")

        # Test without original
        asset = {"id": "123"}
        result = self.mapper._extract_pdf_url(asset)
        self.assertIsNone(result)

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

    @patch("user.related_models.author_model.Author.save")
    def test_map_to_author(self, mock_save):
        """Test mapping author data to Author model."""
        author_data = {
            "first_name": "John",
            "last_name": "Doe",
            "title": "Dr",
            "orcid": "0000-0000-0000-0001",
            "orcid_id": "0000-0000-0000-0001",
            "raw_name": "John Doe",
            "institutions": [{"name": "MIT"}],
        }

        author = self.mapper.map_to_author(author_data)

        self.assertEqual(author.first_name, "John")
        self.assertEqual(author.last_name, "Doe")
        self.assertEqual(author.orcid_id, "0000-0000-0000-0001")
        self.assertEqual(author.created_source, Author.SOURCE_RESEARCHHUB)

        # Check additional attributes
        self.assertEqual(author._raw_name, "John Doe")

    @patch("institution.models.Institution.objects.get")
    @patch("institution.models.Institution.objects.create")
    def test_get_or_create_institution_with_ror(self, mock_create, mock_get):
        """Test institution creation with ROR ID."""
        mock_get.side_effect = Institution.DoesNotExist

        inst_data = {
            "name": "MIT",
            "display_name": "MIT",
            "ror_id": "https://ror.org/042nb2s44",
            "country_code": "US",
        }

        mock_institution = MagicMock(spec=Institution)
        mock_institution.display_name = "MIT"
        mock_create.return_value = mock_institution

        result = self.mapper.get_or_create_institution(inst_data)

        # Check that create was called with correct synthetic IDs
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]
        self.assertEqual(call_args["openalex_id"], "chemrxiv_042nb2s44")
        self.assertEqual(call_args["ror_id"], "https://ror.org/042nb2s44")
        self.assertEqual(call_args["display_name"], "MIT")
        self.assertEqual(call_args["country_code"], "US")

    def test_get_or_create_institution_without_ror(self):
        """Test that institutions without ROR ID are not created."""
        inst_data = {
            "name": "Unknown University",
            "display_name": "Unknown University",
            "country_code": "XX",
        }

        result = self.mapper.get_or_create_institution(inst_data)

        # Should return None for institutions without ROR ID
        self.assertIsNone(result)

    @patch("institution.models.Institution.objects.get")
    def test_get_existing_institution_by_ror(self, mock_get):
        """Test getting existing institution by ROR ID."""
        mock_institution = MagicMock(spec=Institution)
        mock_institution.display_name = "MIT"
        mock_get.return_value = mock_institution

        inst_data = {"name": "MIT", "ror_id": "https://ror.org/042nb2s44"}

        result = self.mapper.get_or_create_institution(inst_data)

        self.assertEqual(result, mock_institution)
        mock_get.assert_called_once_with(ror_id="https://ror.org/042nb2s44")

    @patch.object(ChemRxivMapper, "get_or_create_institution")
    @patch(
        "user.related_models.author_institution.AuthorInstitution.objects.get_or_create"
    )
    def test_create_author_institutions(self, mock_get_or_create, mock_get_inst):
        """Test creating author-institution relationships."""
        # Create mock author with ID
        mock_author = MagicMock(spec=Author)
        mock_author.id = 1
        mock_author.last_name = "Doe"

        # Create mock institution
        mock_institution = MagicMock(spec=Institution)
        mock_institution.display_name = "MIT"
        mock_get_inst.return_value = mock_institution

        # Mock the get_or_create to return a new relationship
        mock_author_inst = MagicMock(spec=AuthorInstitution)
        mock_get_or_create.return_value = (mock_author_inst, True)

        institutions_data = [{"name": "MIT", "ror_id": "https://ror.org/042nb2s44"}]

        result = self.mapper.create_author_institutions(mock_author, institutions_data)

        self.assertEqual(len(result), 1)
        mock_get_or_create.assert_called_once_with(
            author=mock_author, institution=mock_institution, defaults={"years": []}
        )
