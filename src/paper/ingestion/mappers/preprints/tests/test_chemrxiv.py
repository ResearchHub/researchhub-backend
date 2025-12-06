"""
Tests for ChemRxiv mapper.
"""

from unittest.mock import Mock, patch

from django.test import TestCase

from hub.models import Hub
from institution.models import Institution
from paper.ingestion.mappers import ChemRxivMapper
from paper.models import Paper
from paper.related_models.authorship_model import Authorship
from user.related_models.author_model import Author


class TestChemRxivMapper(TestCase):
    """Test ChemRxiv mapper functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.mapper = ChemRxivMapper(None)

        self.chemrxiv_hub, _ = Hub.objects.get_or_create(
            slug="chemrxiv",
            defaults={
                "name": "ChemRxiv",
                "namespace": Hub.Namespace.JOURNAL,
            },
        )

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
        self.assertEqual(paper.pdf_license, "cc-by-nc-nd-4.0")

        # Check URLs
        self.assertEqual(
            paper.pdf_url,
            "https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/68c17d313e708a764924e728/original/paper.pdf",
        )
        self.assertEqual(
            paper.url,
            "https://chemrxiv.org/engage/chemrxiv/article-details/68c17d313e708a764924e728",
        )

        # Check external metadata - should only have chemrxiv_id
        self.assertEqual(
            paper.external_metadata["external_id"], "68c17d313e708a764924e728"
        )
        self.assertEqual(len(paper.external_metadata), 1)

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
            mock_paper = Mock(spec=Paper)
            mock_map.return_value = mock_paper

            results = self.mapper.map_batch(records, validate=True)

            # Should only map the valid record
            self.assertEqual(len(results), 1)
            mock_map.assert_called_once()

    def test_map_to_authors_creates_author_models(self):
        """Test that map_to_authors creates Author model instances."""
        authors = self.mapper.map_to_authors(self.sample_record)

        # Should only create authors with ORCID IDs (1 out of 2)
        self.assertEqual(len(authors), 1)

        # Check the author with ORCID
        self.assertIsInstance(authors[0], Author)
        self.assertEqual(authors[0].first_name, "Péter G.")
        self.assertEqual(authors[0].last_name, "Szalay")
        self.assertEqual(authors[0].orcid_id, "0000-0003-1885-3557")
        self.assertEqual(authors[0].created_source, Author.SOURCE_RESEARCHHUB)

        # Verify private attributes for authorship mapping
        self.assertTrue(hasattr(authors[0], "_raw_name"))
        self.assertTrue(hasattr(authors[0], "_institutions_data"))
        self.assertTrue(hasattr(authors[0], "_index"))
        self.assertEqual(authors[0]._index, 1)  # Second author in list
        self.assertEqual(authors[0]._total_authors, 2)

    def test_map_to_authors_skips_without_orcid(self):
        """Test that authors without ORCID are skipped."""
        record = {
            "authors": [
                {"firstName": "No", "lastName": "Orcid", "orcid": ""},
                {"firstName": "Also No", "lastName": "Orcid"},  # Missing orcid field
                {"firstName": "Has", "lastName": "Orcid", "orcid": None},  # None value
            ]
        }

        authors = self.mapper.map_to_authors(record)
        self.assertEqual(len(authors), 0)

    def test_map_to_authors_with_multiple_orcids(self):
        """Test mapping multiple authors with ORCIDs."""
        record = {
            "authors": [
                {
                    "firstName": "John",
                    "lastName": "Doe",
                    "orcid": "0000-0001-2345-6789",
                    "institutions": [
                        {
                            "name": "Test University",
                            "rorId": "https://ror.org/test123",
                            "country": "United States",
                        }
                    ],
                },
                {
                    "firstName": "Jane",
                    "lastName": "Smith",
                    "orcid": "0000-0002-3456-7890",
                    "institutions": [],
                },
                {
                    "firstName": "Bob",
                    "lastName": "NoOrcid",
                    "orcid": "",  # No ORCID
                    "institutions": [],
                },
            ],
        }

        authors = self.mapper.map_to_authors(record)

        # Should only create authors with ORCID IDs (2 out of 3)
        self.assertEqual(len(authors), 2)

        # Check first author
        self.assertEqual(authors[0].first_name, "John")
        self.assertEqual(authors[0].last_name, "Doe")
        self.assertEqual(authors[0].orcid_id, "0000-0001-2345-6789")

        # Check second author
        self.assertEqual(authors[1].first_name, "Jane")
        self.assertEqual(authors[1].last_name, "Smith")
        self.assertEqual(authors[1].orcid_id, "0000-0002-3456-7890")

    def test_map_to_authors_empty_record(self):
        """Test handling of empty author list."""
        authors = self.mapper.map_to_authors({"authors": []})
        self.assertEqual(authors, [])

        authors = self.mapper.map_to_authors({})  # Missing authors field
        self.assertEqual(authors, [])

    def test_map_to_institutions_creates_institution_models(self):
        """Test that map_to_institutions creates Institution model instances."""
        institutions = self.mapper.map_to_institutions(self.sample_record)

        # Should only create institutions with ROR IDs (1 out of 2)
        self.assertEqual(len(institutions), 1)

        # Check the institution with ROR ID
        inst = institutions[0]
        self.assertIsInstance(inst, Institution)
        self.assertEqual(inst.ror_id, "https://ror.org/01s2bdc37")
        self.assertIsNotNone(inst.openalex_id)
        self.assertIn("chemrxiv_", inst.openalex_id)  # Synthetic ID
        self.assertEqual(inst.display_name, "ELTE Eötvös Loránd University")
        self.assertEqual(inst.country_code, "HU")
        self.assertEqual(inst.type, "education")
        self.assertEqual(inst.lineage, [])
        self.assertEqual(inst.associated_institutions, [])

    def test_map_to_institutions_deduplicates(self):
        """Test that duplicate institutions are deduplicated by ROR ID."""
        record = {
            "authors": [
                {
                    "institutions": [
                        {"name": "Uni A", "rorId": "https://ror.org/same"},
                        {"name": "Uni B", "rorId": "https://ror.org/different"},
                    ]
                },
                {
                    "institutions": [
                        {"name": "Uni A", "rorId": "https://ror.org/same"},  # Duplicate
                    ]
                },
            ]
        }

        institutions = self.mapper.map_to_institutions(record)
        self.assertEqual(len(institutions), 2)  # Only 2 unique ROR IDs

    def test_map_to_institutions_skips_without_ror(self):
        """Test that institutions without ROR ID are skipped."""
        record = {
            "authors": [
                {
                    "institutions": [
                        {"name": "No ROR", "rorId": ""},
                        {"name": "Also No ROR"},  # Missing rorId field
                        {"name": "Has ROR", "rorId": "https://ror.org/valid"},
                    ]
                }
            ]
        }

        institutions = self.mapper.map_to_institutions(record)
        self.assertEqual(len(institutions), 1)  # Only the one with ROR ID
        self.assertEqual(institutions[0].display_name, "Has ROR")

    def test_map_to_institutions_multiple_unique(self):
        """Test mapping multiple unique institutions."""
        record = {
            "authors": [
                {
                    "institutions": [
                        {
                            "name": "University A",
                            "rorId": "https://ror.org/test123",
                            "country": "United States",
                        },
                        {
                            "name": "University B",
                            "rorId": "https://ror.org/test456",
                            "country": "United Kingdom",
                        },
                    ]
                },
                {
                    "institutions": [
                        {
                            "name": "University C",
                            "rorId": "https://ror.org/test789",
                            "country": "Canada",
                        }
                    ]
                },
            ]
        }

        institutions = self.mapper.map_to_institutions(record)
        self.assertEqual(len(institutions), 3)

        # Check ROR IDs
        ror_ids = [inst.ror_id for inst in institutions]
        self.assertIn("https://ror.org/test123", ror_ids)
        self.assertIn("https://ror.org/test456", ror_ids)
        self.assertIn("https://ror.org/test789", ror_ids)

        # Check display names
        names = [inst.display_name for inst in institutions]
        self.assertIn("University A", names)
        self.assertIn("University B", names)
        self.assertIn("University C", names)

    def test_map_to_authorships_creates_authorship_models(self):
        """Test that map_to_authorships creates Authorship model instances."""
        # Create a paper for the test
        paper = Paper(
            id=1,  # Fake ID for testing
            title="Test Paper",
            doi="10.1234/test",
            external_source="chemrxiv",
        )

        authorships = self.mapper.map_to_authorships(paper, self.sample_record)

        # Should create authorships only for authors with ORCID (1 out of 2)
        self.assertEqual(len(authorships), 1)

        # Check the authorship
        authorship = authorships[0]
        self.assertIsInstance(authorship, Authorship)
        self.assertEqual(authorship.paper, paper)
        self.assertIsInstance(authorship.author, Author)
        self.assertEqual(authorship.author.first_name, "Péter G.")
        self.assertEqual(authorship.author.last_name, "Szalay")
        self.assertEqual(authorship.author_position, "last")  # Last of 2 authors
        self.assertEqual(authorship.raw_author_name, "Péter G. Szalay")

        # Check institutions to add
        self.assertTrue(hasattr(authorship, "_institutions_to_add"))
        self.assertEqual(len(authorship._institutions_to_add), 1)
        self.assertEqual(
            authorship._institutions_to_add[0].display_name,
            "ELTE Eötvös Loránd University",
        )

    def test_map_to_authorships_positions(self):
        """Test correct assignment of author positions."""
        record = {
            "authors": [
                {
                    "firstName": "First",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0001",
                    "institutions": [],
                },
                {
                    "firstName": "Middle",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0002",
                    "institutions": [],
                },
                {
                    "firstName": "Last",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0003",
                    "institutions": [],
                },
            ]
        }

        paper = Paper(id=1, title="Test", doi="test")
        authorships = self.mapper.map_to_authorships(paper, record)

        self.assertEqual(authorships[0].author_position, "first")
        self.assertEqual(authorships[1].author_position, "middle")
        self.assertEqual(authorships[2].author_position, "last")

    def test_map_to_authorships_single_author(self):
        """Test position for single author."""
        record = {
            "authors": [
                {
                    "firstName": "Solo",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0001",
                    "institutions": [],
                }
            ]
        }

        paper = Paper(id=1, title="Test", doi="test")
        authorships = self.mapper.map_to_authorships(paper, record)

        self.assertEqual(len(authorships), 1)
        # Single author is "first" (index 0)
        self.assertEqual(authorships[0].author_position, "first")

    def test_map_to_authorships_two_authors(self):
        """Test positions for two authors (first and last)."""
        record = {
            "authors": [
                {
                    "firstName": "First",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0001",
                    "institutions": [],
                },
                {
                    "firstName": "Second",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0002",
                    "institutions": [],
                },
            ]
        }

        paper = Paper(id=1, title="Test", doi="test")
        authorships = self.mapper.map_to_authorships(paper, record)

        self.assertEqual(len(authorships), 2)
        self.assertEqual(authorships[0].author_position, "first")
        self.assertEqual(authorships[1].author_position, "last")

    def test_map_to_authorships_institution_matching(self):
        """Test that institutions are correctly matched to authorships."""
        record = {
            "authors": [
                {
                    "firstName": "Test",
                    "lastName": "Author",
                    "orcid": "0000-0000-0000-0001",
                    "institutions": [
                        {"name": "University A", "rorId": "https://ror.org/a"},
                        {"name": "University B", "rorId": "https://ror.org/b"},
                    ],
                }
            ]
        }

        paper = Paper(id=1, title="Test", doi="test")
        authorships = self.mapper.map_to_authorships(paper, record)

        # Should have matched both institutions
        self.assertEqual(len(authorships[0]._institutions_to_add), 2)

        # Check institution names
        inst_names = [inst.display_name for inst in authorships[0]._institutions_to_add]
        self.assertIn("University A", inst_names)
        self.assertIn("University B", inst_names)

    def test_map_to_authorships_mixed_orcids(self):
        """Test authorships with mixed ORCID presence."""
        record = {
            "authors": [
                {
                    "firstName": "Has",
                    "lastName": "Orcid",
                    "orcid": "0000-0000-0000-0001",
                    "institutions": [],
                },
                {
                    "firstName": "No",
                    "lastName": "Orcid",
                    "orcid": "",  # No ORCID
                    "institutions": [],
                },
                {
                    "firstName": "Also Has",
                    "lastName": "Orcid",
                    "orcid": "0000-0000-0000-0003",
                    "institutions": [],
                },
            ]
        }

        paper = Paper(id=1, title="Test", doi="test")
        authorships = self.mapper.map_to_authorships(paper, record)

        # Should only create authorships for authors with ORCID (2 out of 3)
        self.assertEqual(len(authorships), 2)

        # First author with ORCID is at index 0, so position is "first"
        self.assertEqual(authorships[0].author_position, "first")
        # Second author with ORCID is at index 2 (last), so position is "last"
        self.assertEqual(authorships[1].author_position, "last")

    def test_map_to_hubs(self):
        """
        Test map_to_hubs returns expected hubs including chemrxiv hub.
        """
        # Arrange
        mock_hub_mapper = Mock()
        chemistry_hub, _ = Hub.objects.get_or_create(
            slug="chemistry",
            defaults={"name": "Chemistry"},
        )
        mock_hub_mapper.map.return_value = [chemistry_hub]

        mapper = ChemRxivMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        # Should be called twice (once for each category)
        self.assertEqual(mock_hub_mapper.map.call_count, 2)
        self.assertEqual(len(hubs), 2)
        self.assertIn(chemistry_hub, hubs)
        self.assertIn(self.chemrxiv_hub, hubs)

        # Verify category mapping was called with correct parameters
        mock_hub_mapper.map.assert_any_call(
            source_category="Theoretical and Computational Chemistry",
            source="chemrxiv",
        )
        mock_hub_mapper.map.assert_any_call(
            source_category="Computational Chemistry and Modeling",
            source="chemrxiv",
        )

    def test_map_to_hubs_without_hub_mapper(self):
        """
        Test map_to_hubs falls back to default behavior without hub_mapper,
        i.e., only returning the journal hub.
        """
        # Arrange
        mapper = ChemRxivMapper(None)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.chemrxiv_hub)

    def test_map_to_hubs_no_duplicate_chemrxiv_hub(self):
        """
        Test that chemrxiv hub is not duplicated if already returned by hub_mapper.
        """
        # Arrange
        mock_hub_mapper = Mock()
        chemistry_hub, _ = Hub.objects.get_or_create(
            slug="chemistry",
            defaults={"name": "Chemistry"},
        )
        # hub_mapper returns both hubs including the chemrxiv hub
        mock_hub_mapper.map.return_value = [chemistry_hub, self.chemrxiv_hub]

        mapper = ChemRxivMapper(mock_hub_mapper)
        paper = mapper.map_to_paper(self.sample_record)

        # Act
        hubs = mapper.map_to_hubs(self.sample_record)

        # Assert
        # Should only have 2 hubs, not duplicate the chemrxiv hub
        self.assertEqual(len(hubs), 2)
        self.assertEqual(hubs.count(self.chemrxiv_hub), 1)  # Only appears once
        self.assertIn(chemistry_hub, hubs)
        self.assertIn(self.chemrxiv_hub, hubs)

    def test_map_to_hubs_without_categories(self):
        """
        Test map_to_hubs with record that has no categories field.
        """
        # Arrange
        mock_hub_mapper = Mock()
        mapper = ChemRxivMapper(mock_hub_mapper)

        record_no_categories = {**self.sample_record}
        del record_no_categories["categories"]
        paper = mapper.map_to_paper(record_no_categories)

        # Act
        hubs = mapper.map_to_hubs(record_no_categories)

        # Assert
        mock_hub_mapper.map.assert_not_called()
        self.assertEqual(len(hubs), 1)
        self.assertEqual(hubs[0], self.chemrxiv_hub)

    def test_parse_license(self):
        """
        Test license parsing from BioRxiv license strings.
        """
        # Arrange
        test_cases = {
            "CC BY 4.0": "cc-by-4.0",
            "CC BY NC 4.0": "cc-by-nc-4.0",
            "CC BY NC ND 4.0": "cc-by-nc-nd-4.0",
            "": None,
            None: None,
        }

        for given, expected in test_cases.items():
            with self.subTest(given=given, expected=expected):
                # Act
                result = self.mapper._parse_license(given)
                # Assert
                self.assertEqual(result, expected)
